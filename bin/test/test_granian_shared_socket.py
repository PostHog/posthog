#!/usr/bin/env python3

import os
import sys
import time
import signal
import socket
import threading
import subprocess
import http.client
from pathlib import Path
from tempfile import TemporaryDirectory

import unittest

LAUNCHER = Path(__file__).resolve().parents[1] / "granian_shared_socket.py"

APP = """
import os
import time


def app(environ, start_response):
    if environ["PATH_INFO"] == "/slow":
        open(os.environ["SLOW_MARKER"], "w").close()
        time.sleep(10)
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"ok"]
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def count_listen_sockets(port: int) -> int:
    suffix = f":{port:04X}"
    count = 0
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        for line in Path(table).read_text().splitlines()[1:]:
            fields = line.split()
            # State 0A is TCP_LISTEN.
            if fields[1].endswith(suffix) and fields[3] == "0A":
                count += 1
    return count


def get(port: int, path: str, timeout: float) -> str:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        return str(conn.getresponse().status)
    except OSError as error:
        return type(error).__name__
    finally:
        conn.close()


@unittest.skipUnless(sys.platform == "linux", "granian splits listen sockets per worker only on Linux")
class TestGranianSharedSocket(unittest.TestCase):
    """Boots bin/granian_shared_socket.py the way the query pool runs it: 4 workers, one request each."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TemporaryDirectory()
        Path(cls.tmp.name, "app.py").write_text(APP)
        cls.slow_marker = Path(cls.tmp.name, "slow.started")
        cls.port = free_port()
        env = {key: value for key, value in os.environ.items() if not key.startswith("GRANIAN_")}
        env.update(
            GRANIAN_INTERFACE="wsgi",
            GRANIAN_HOST="127.0.0.1",
            GRANIAN_PORT=str(cls.port),
            GRANIAN_WORKERS="4",
            GRANIAN_BLOCKING_THREADS="1",
            GRANIAN_BACKPRESSURE="1",
            GRANIAN_HTTP1_KEEP_ALIVE="false",
            GRANIAN_WORKERS_KILL_TIMEOUT="1",
            GRANIAN_LOG_LEVEL="error",
            SLOW_MARKER=str(cls.slow_marker),
        )
        cls.server = subprocess.Popen(
            [sys.executable, str(LAUNCHER), "app:app"],
            cwd=cls.tmp.name,
            env=env,
            start_new_session=True,
        )
        deadline = time.monotonic() + 30
        while get(cls.port, "/", timeout=1) != "200":
            if cls.server.poll() is not None or time.monotonic() > deadline:
                cls.tearDownClass()
                raise RuntimeError("granian did not start")
            time.sleep(0.2)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        try:
            cls.server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(cls.server.pid, signal.SIGKILL)
            cls.server.wait()
        cls.tmp.cleanup()

    def test_workers_share_one_listen_socket(self) -> None:
        self.assertEqual(count_listen_sockets(self.port), 1)

    def test_busy_worker_does_not_hold_new_connections(self) -> None:
        threading.Thread(target=get, args=(self.port, "/slow", 30), daemon=True).start()
        deadline = time.monotonic() + 10
        while not self.slow_marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.slow_marker.exists(), "the /slow request never reached a worker")
        # With per-worker sockets about a quarter of these land on the busy worker and time out.
        statuses = [get(self.port, "/", timeout=2) for _ in range(20)]
        self.assertEqual(statuses, ["200"] * 20)


if __name__ == "__main__":
    unittest.main()
