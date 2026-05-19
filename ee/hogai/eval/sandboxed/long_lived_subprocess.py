from __future__ import annotations

import os
import time
import atexit
import signal
import socket
import logging
import threading
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import FrameType

import pytest

logger = logging.getLogger(__name__)

StopCallback = Callable[[], None]


class LongLivedSubprocessManager:
    """Own support subprocess lifecycle for sandboxed eval sessions."""

    def __init__(self) -> None:
        self._stops: list[StopCallback] = []
        self._stops_lock = threading.Lock()
        self._previous_signal_handlers: dict[int, object] = {}
        self._signal_handlers_installed = False
        self._handling_termination_signal = False

    def start(
        self,
        *,
        name: str,
        port: int,
        cmd: list[str],
        cwd: Path,
        env: dict[str, str],
        log_prefix: str,
        readiness_timeout: float = 30.0,
    ) -> tuple[subprocess.Popen, StopCallback]:
        """Spawn a long-lived support service for the eval session.

        Three guarantees beyond a bare ``subprocess.Popen``:

        * **Pre-flight port check** — refuses to start if ``port`` is already
          bound. A stale process would otherwise pass readiness checks and run
          against the wrong test database.
        * **Subprocess-aware readiness wait** — polls ``proc.poll()`` while
          waiting for the port, so early startup failures fail loudly.
        * **Process-group cleanup on exit / interrupt** — fixture teardown,
          an ``atexit`` hook, and SIGINT/SIGTERM handlers send ``SIGTERM``
          then ``SIGKILL`` to the process group.
        """
        self._fail_if_port_bound(name, port)

        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )

        def stop() -> None:
            try:
                self._stop_process_group(proc)
            finally:
                self._unregister(stop)

        self._register(stop)
        atexit.register(stop)
        self._pipe_output(proc, log_prefix)

        deadline = time.monotonic() + readiness_timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stop()
                pytest.fail(
                    f"{name} subprocess exited with code {proc.returncode} during startup. "
                    f"Check the [{log_prefix}] WARNING lines above."
                )
            try:
                sock = socket.create_connection(("localhost", port), timeout=1)
                sock.close()
                return proc, stop
            except OSError:
                time.sleep(0.5)

        stop()
        pytest.fail(f"{name} failed to start on port {port} within {readiness_timeout:.0f}s.")

    def stop_all(self) -> None:
        with self._stops_lock:
            stops = list(reversed(self._stops))

        for stop in stops:
            try:
                stop()
            except Exception:
                logger.warning("Failed to stop sandboxed eval support subprocess", exc_info=True)

    def _fail_if_port_bound(self, name: str, port: int) -> None:
        try:
            pre_sock = socket.create_connection(("localhost", port), timeout=0.5)
            pre_sock.close()
            pytest.fail(
                f"Port {port} is already in use — likely a stale {name} from a prior eval session. "
                f"Find and kill it:\n  lsof -iTCP:{port} -sTCP:LISTEN"
            )
        except OSError:
            pass

    def _stop_process_group(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def _pipe_output(self, proc: subprocess.Popen, log_prefix: str) -> None:
        def pipe_to_logger(pipe, level: int) -> None:
            for line in iter(pipe.readline, b""):
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.log(level, "[%s] %s", log_prefix, text)
            pipe.close()

        if proc.stdout is not None:
            threading.Thread(target=pipe_to_logger, args=(proc.stdout, logging.INFO), daemon=True).start()
        if proc.stderr is not None:
            threading.Thread(target=pipe_to_logger, args=(proc.stderr, logging.WARNING), daemon=True).start()

    def _register(self, stop: StopCallback) -> None:
        self._install_signal_handlers()
        with self._stops_lock:
            self._stops.append(stop)

    def _unregister(self, stop: StopCallback) -> None:
        with self._stops_lock:
            try:
                self._stops.remove(stop)
            except ValueError:
                pass

    def _install_signal_handlers(self) -> None:
        if self._signal_handlers_installed:
            return

        if threading.current_thread() is not threading.main_thread():
            return

        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous_signal_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle_termination_signal)

        self._signal_handlers_installed = True

    def _handle_termination_signal(self, signum: int, frame: FrameType | None) -> None:
        if self._handling_termination_signal:
            return

        self._handling_termination_signal = True
        try:
            self.stop_all()
        finally:
            self._handling_termination_signal = False

        self._delegate_to_previous_signal_handler(signum, frame)

    def _delegate_to_previous_signal_handler(self, signum: int, frame: FrameType | None) -> None:
        previous_handler = self._previous_signal_handlers.get(signum, signal.SIG_DFL)

        if callable(previous_handler):
            previous_handler(signum, frame)
            return

        if previous_handler == signal.SIG_IGN:
            return

        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
