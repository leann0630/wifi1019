
import network
import socket
import time
import machine
import ujson
import os
import ure
import urequests

# ===== WiFi =====
ssid = "labor"
password = "98668800"

# ===== OTA version =====
CURRENT_VERSION = "1.0.1"

# 填入實際 GitHub Pages 網址
VERSION_URL = "https://leann0630.github.io/wifi1019/version.json"

# 每 6 小時檢查一次
OTA_CHECK_INTERVAL = 6 * 60 * 60
last_ota_check = time.time()

# ===== WiFi connection =====
wifi = network.WLAN(network.STA_IF)
wifi.active(True)

if not wifi.isconnected():
    wifi.connect(ssid, password)

while not wifi.isconnected():
    print("Connecting to WiFi...")
    time.sleep(1)

print("WiFi connected:", wifi.ifconfig()[0])

# ===== Version comparison =====
def is_newer_version(remote, current):
    try:
        r = [int(x) for x in remote.split(".")]
        c = [int(x) for x in current.split(".")]

        while len(r) < 3:
            r.append(0)
        while len(c) < 3:
            c.append(0)

        return tuple(r) > tuple(c)
    except Exception:
        return False

# ===== GitHub OTA check =====
def check_for_update():
    global CURRENT_VERSION

    if not wifi.isconnected():
        print("[OTA] WiFi disconnected")
        return "WiFi disconnected"

    response = None

    try:
        print("[OTA] Checking GitHub version...")

        response = urequests.get(VERSION_URL)
        if response.status_code != 200:
            print("[OTA] HTTP error:", response.status_code)
            return "Version HTTP error"

        doc = response.json()

    except Exception as e:
        print("[OTA] Version check failed:", repr(e))
        return "Version check failed"

    finally:
        if response:
            response.close()

    remote_version = doc.get("version")
    firmware_url = doc.get("firmware")

    if not remote_version or not firmware_url:
        print("[OTA] Missing version or firmware URL")
        return "Invalid version.json"

    print("[OTA] Current:", CURRENT_VERSION)
    print("[OTA] GitHub:", remote_version)

    if not is_newer_version(remote_version, CURRENT_VERSION):
        print("[OTA] Already up to date")
        return "Already up to date"

    # 此版本更新的是 MicroPython main.py 程式碼，
    # 不是 Arduino 的 .bin 韌體。
    if not firmware_url.startswith("https://"):
        return "Invalid firmware URL"

    response = None

    try:
        print("[OTA] Downloading Python program...")

        response = urequests.get(firmware_url)

        if response.status_code != 200:
            return "Download failed"

        new_code = response.text

        if not new_code.strip():
            return "Empty program"

        # 先寫入暫存檔
        with open("main_new.py", "w") as f:
            f.write(new_code)

        print("[OTA] Download complete")

        # 保留原始程式作為備份
        try:
            os.remove("main_backup.py")
        except OSError:
            pass

        try:
            os.rename("main.py", "main_backup.py")
        except OSError:
            print("[OTA] main.py backup skipped")

        os.rename("main_new.py", "main.py")

        CURRENT_VERSION = remote_version

        print("[OTA] Program updated; rebooting")
        time.sleep(1)
        machine.reset()

    except Exception as e:
        print("[OTA] Update failed:", repr(e))
        return "Update failed"

    finally:
        if response:
            response.close()

    return "Update finished"

# ===== HTML pages =====
login_html = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 Login</title>
</head>
<body>
<h2>ESP32 Login Page</h2>
<form action="/login" method="POST">
Username: <input name="userid"><br><br>
Password: <input type="password" name="pwd"><br><br>
<button type="submit">Login</button>
</form>
</body>
</html>
"""

ota_html = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 GitHub OTA</title>
</head>
<body>
<h2>ESP32 GitHub OTA</h2>
<p>Automatic version checking is enabled.</p>
<form action="/check" method="POST">
<button type="submit">Check GitHub Version Now</button>
</form>
</body>
</html>
"""

# ===== Simple HTTP server =====
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", 80))
server.listen(5)
server.settimeout(1)

print("Web server started")
print("Open http://" + wifi.ifconfig()[0] + "/")

# 開機檢查一次
check_for_update()
last_ota_check = time.time()

while True:
    # 每 6 小時檢查
    if time.time() - last_ota_check >= OTA_CHECK_INTERVAL:
        last_ota_check = time.time()
        check_for_update()

    try:
        conn, addr = server.accept()
    except OSError:
        continue

    try:
        conn.settimeout(3)
        request = conn.recv(2048).decode()
        request_line = request.split("\r\n")[0]
        print(request_line)

        method = request_line.split(" ")[0]
        path = request_line.split(" ")[1]

        body = ""
        status = "200 OK"
        content_type = "text/html; charset=utf-8"

        if path == "/":
            body = login_html

        elif path == "/login" and method == "POST":
            form_data = request.split("\r\n\r\n", 1)
            data = form_data[1] if len(form_data) > 1 else ""

            # 簡單解析 HTML 表單
            fields = {}
            for item in data.split("&"):
                pair = item.split("=", 1)
                if len(pair) == 2:
                    fields[pair[0]] = pair[1].replace("+", " ")

            if fields.get("userid") == "admin" and \
               fields.get("pwd") == "admin":
                body = """<html><body>
                <h2>Login successful</h2>
                <a href="/serverIndex">Open OTA page</a>
                </body></html>"""
            else:
                status = "401 Unauthorized"
                body = "Wrong username or password"
                content_type = "text/plain"

        elif path == "/serverIndex":
            body = ota_html

        elif path == "/check" and method == "POST":
            # 先回覆瀏覽器，再執行耗時的更新檢查
            body = "Version check started. See serial output."
            content_type = "text/plain"

        else:
            status = "404 Not Found"
            body = "Not found"
            content_type = "text/plain"

        response = (
            "HTTP/1.1 " + status + "\r\n"
            "Content-Type: " + content_type + "\r\n"
            "Connection: close\r\n\r\n" + body
        )

        conn.send(response.encode())

        # 手動檢查更新
        if path == "/check" and method == "POST":
            conn.close()
            conn = None
            check_for_update()
            last_ota_check = time.time()
            continue

    except Exception as e:
        print("HTTP error:", repr(e))

    finally:
        if conn:
            conn.close()
