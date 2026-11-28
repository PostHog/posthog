#!/usr/bin/env python3

import os
import sys
import time
import signal
import socket
import subprocess
import http.client
from pathlib import Path
from tempfile import TemporaryDirectory

import unittest

from parameterized import parameterized
from test_granian_shared_socket import count_listen_sockets

LAUNCHER = Path(__file__).resolve().parents[1] / "granian_preload.py"

APP = """
import os

IMPORTED_BY = os.getpid()


def body():
    return f"{IMPORTED_BY} {os.getpid()}".encode()


def wsgi_app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [body()]


async def asgi_app(scope, receive, send):
    if scope["type"] == "lifespan":
        while (await receive())["type"] != "lifespan.shutdown":
            await send({"type": "lifespan.startup.complete"})
        await send({"type": "lifespan.shutdown.complete"})
        return
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": body()})
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get(port: int) -> str | None:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request("GET", "/")
        return conn.getresponse().read().decode()
    except OSError:
        return None
    finally:
        conn.close()


# What an app can leave behind at import, and whether the workers can still fork from the parent.
THREAD_LEFT_RUNNING = """
import threading, time
threading.Thread(target=time.sleep, args=(600,), daemon=True).start()
"""
STREAM_SOCKET_LEFT_OPEN = """
import socket
KEPT = socket.socketpair()
"""
DATAGRAM_SOCKET_LEFT_OPEN = """
import socket
KEPT = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
"""
# polars starts a thread when it loads, so the launcher defers it until a worker uses it.
THREAD_STARTING_LIBRARY_IMPORTED = """
import polars

_body = body


def body():
    return _body() + f" {polars.DataFrame({'a': [1, 2]}).height}".encode()
"""


@unittest.skipUnless(sys.platform == "linux", "hobby runs granian on Linux")
class TestGranianPreload(unittest.TestCase):
    def serve(self, interface: str, shared_socket: str, app: str) -> tuple[dict[int, int], int, int, str, set[str]]:
        """
        Start the launcher, ask until both workers answered, and return which process imported
        the app that each worker runs, the launcher pid, the listen socket count, stderr and
        any further words that the app put in its answers.
        """
        with TemporaryDirectory() as tmp:
            Path(tmp, "app.py").write_text(app)
            port = free_port()
            env = {key: value for key, value in os.environ.items() if not key.startswith("GRANIAN_")}
            env.update(
                GRANIAN_INTERFACE=interface,
                GRANIAN_HOST="127.0.0.1",
                GRANIAN_PORT=str(port),
                GRANIAN_WORKERS="2",
                GRANIAN_WORKERS_KILL_TIMEOUT="1",
                GRANIAN_LOG_LEVEL="error",
                POSTHOG_GRANIAN_SHARED_SOCKET=shared_socket,
            )
            stderr_path = Path(tmp, "stderr")
            with stderr_path.open("w") as stderr:
                server = subprocess.Popen(
                    [sys.executable, str(LAUNCHER), f"app:{interface}_app"],
                    cwd=tmp,
                    env=env,
                    stderr=stderr,
                    start_new_session=True,
                )
            try:
                deadline = time.monotonic() + 60
                importer_by_worker: dict[int, int] = {}
                extra_words: set[str] = set()
                # A worker opens its own listen socket when it starts, so count the sockets only
                # after both workers have answered.
                while len(importer_by_worker) < 2:
                    if server.poll() is not None or time.monotonic() > deadline:
                        self.fail(f"granian did not start both workers: {stderr_path.read_text()}")
                    if (body := get(port)) is None:
                        time.sleep(0.2)
                        continue
                    imported_by, served_by = (int(pid) for pid in body.split()[:2])
                    extra_words.update(body.split()[2:])
                    importer_by_worker[served_by] = imported_by
                return importer_by_worker, server.pid, count_listen_sockets(port), stderr_path.read_text(), extra_words
            finally:
                server.terminate()
                try:
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait()

    @parameterized.expand(
        [
            ("asgi", "false", True, 2),
            ("wsgi", "false", False, 2),
            ("asgi", "true", True, 1),
            ("wsgi", "true", False, 1),
        ]
    )
    def test_workers_share_the_parent_import_under_asgi_and_one_socket_on_request(
        self, interface: str, shared_socket: str, preloaded: bool, listen_sockets: int
    ) -> None:
        importer_by_worker, server_pid, sockets, _, _ = self.serve(interface, shared_socket, APP)

        self.assertNotIn(server_pid, importer_by_worker)
        self.assertEqual([imported_by == server_pid for imported_by in importer_by_worker.values()], [preloaded] * 2)
        self.assertEqual(sockets, listen_sockets)

    @parameterized.expand(
        [
            ("thread_left_running", THREAD_LEFT_RUNNING, False, set()),
            ("stream_socket_left_open", STREAM_SOCKET_LEFT_OPEN, False, set()),
            ("datagram_socket_left_open", DATAGRAM_SOCKET_LEFT_OPEN, True, set()),
            ("thread_starting_library_imported", THREAD_STARTING_LIBRARY_IMPORTED, True, {"2"}),
        ]
    )
    def test_workers_fork_from_the_parent_only_when_the_import_leaves_it_safe_to_fork(
        self, _name: str, import_side_effect: str, preloaded: bool, words_from_import: set[str]
    ) -> None:
        importer_by_worker, server_pid, _, stderr, extra_words = self.serve("asgi", "false", APP + import_side_effect)

        self.assertEqual([imported_by == server_pid for imported_by in importer_by_worker.values()], [preloaded] * 2)
        self.assertEqual("so each worker imports the app itself" in stderr, not preloaded)
        self.assertEqual(extra_words, words_from_import)


if __name__ == "__main__":
    unittest.main()
