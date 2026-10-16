import os
import sys
import json
import signal
import socket
import logging
import threading
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from types import FrameType
from typing import TYPE_CHECKING

from django.conf import settings

from posthog.temporal.common import memory_profiler_process
from posthog.temporal.common.memory_profiler_process import MemoryProfilerConfig

if TYPE_CHECKING:
    import memray

logger = logging.getLogger(__name__)


def startup_timeout(signum: int, frame: FrameType | None) -> None:
    raise TimeoutError("Memray collector did not connect before the startup deadline")


class MemoryProfiler:
    def __init__(self, config: MemoryProfilerConfig) -> None:
        self.config = config
        self.supervisor: subprocess.Popen[bytes] | None = None
        self.control: socket.socket | None = None
        self.tracker: memray.Tracker | None = None
        self.collector_pid: int | None = None
        self.metrics_port: int | None = None

    def start(self) -> None:
        if sys.platform != "linux" or threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Worker memory profiling requires Linux and startup on the main thread")
        if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
            raise RuntimeError("Worker memory profiling cannot replace an existing alarm")
        import memray  # noqa: PLC0415 - disabled workers must not import the native profiler

        control, child_control = socket.socketpair()
        self.control = control
        try:
            self.supervisor = subprocess.Popen(
                [
                    sys.executable,
                    memory_profiler_process.__file__,
                    "supervise",
                    json.dumps(asdict(self.config)),
                    str(child_control.fileno()),
                    "0",
                    str(os.getpid()),
                ],
                pass_fds=(child_control.fileno(),),
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        finally:
            child_control.close()
        control.settimeout(self.config.startup_timeout_seconds)
        with control.makefile("rb") as response:
            ready = json.loads(response.readline(4096))
        self.collector_pid = ready["collector_pid"]
        self.metrics_port = ready["metrics_port"]
        previous_handler = signal.signal(signal.SIGALRM, startup_timeout)
        signal.setitimer(signal.ITIMER_REAL, self.config.startup_timeout_seconds)
        try:
            tracker = memray.Tracker(
                destination=memray.SocketDestination(server_port=ready["stream_port"], address="127.0.0.1"),
                native_traces=self.config.native_traces,
            )
            tracker.__enter__()
            self.tracker = tracker
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

    def stop(self) -> None:
        # Close the reader first so Tracker.__exit__ cannot block flushing a full socket.
        if self.control is not None:
            self.control.close()
        if self.supervisor is not None:
            try:
                self.supervisor.wait(timeout=7)
            except subprocess.TimeoutExpired:
                os.killpg(self.supervisor.pid, signal.SIGKILL)
                self.supervisor.wait(timeout=5)
        if self.tracker is not None:
            self.tracker.__exit__(None, None, None)
            self.tracker = None


@contextmanager
def profile_worker_memory(task_queue: str) -> Iterator[None]:
    if not settings.TEMPORAL_MEMRAY_ENABLED:
        yield
        return
    profiler = MemoryProfiler(
        MemoryProfilerConfig(
            metrics_port=settings.TEMPORAL_MEMRAY_METRICS_PORT,
            native_traces=settings.TEMPORAL_MEMRAY_NATIVE_TRACES,
            snapshot_interval_seconds=settings.TEMPORAL_MEMRAY_SNAPSHOT_INTERVAL_SECONDS,
            log_interval_seconds=settings.TEMPORAL_MEMRAY_LOG_INTERVAL_SECONDS,
            top_stacks=settings.TEMPORAL_MEMRAY_TOP_STACKS,
            startup_timeout_seconds=settings.TEMPORAL_MEMRAY_STARTUP_TIMEOUT_SECONDS,
            watchdog_timeout_seconds=settings.TEMPORAL_MEMRAY_WATCHDOG_TIMEOUT_SECONDS,
            collector_max_rss_mb=settings.TEMPORAL_MEMRAY_COLLECTOR_MAX_RSS_MB,
            task_queue=task_queue,
        )
    )
    try:
        try:
            profiler.start()
        except Exception:
            profiler.stop()
            logger.exception("Temporal memory profiling could not start; continuing without profiling")
        yield
    finally:
        profiler.stop()
