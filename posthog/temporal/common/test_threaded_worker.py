import time
import asyncio

import pytest

from posthog.temporal.common.test_utils import ThreadedWorker


class _FakeWorker(ThreadedWorker):
    def __init__(self) -> None:
        # Match the base Worker's asyncio.Event type; only .set()/.is_set() are used (both sync).
        self._shutdown_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return False


class _WorkerDiesOnStartup(_FakeWorker):
    def run_using_loop(self, loop) -> None:
        raise RuntimeError("simulated worker boot failure")


class _WorkerNeverReady(_FakeWorker):
    def run_using_loop(self, loop) -> None:
        while not self._shutdown_event.is_set():
            time.sleep(0.05)


def test_run_in_thread_surfaces_worker_startup_failure():
    with pytest.raises(RuntimeError, match="failed to start") as exc_info:
        with _WorkerDiesOnStartup().run_in_thread():
            pass

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "simulated worker boot failure" in str(exc_info.value.__cause__)


def test_run_in_thread_times_out_when_worker_never_starts():
    started = time.monotonic()

    with pytest.raises(TimeoutError, match="did not start within"):
        with _WorkerNeverReady().run_in_thread(startup_timeout=0.5):
            pass

    assert time.monotonic() - started < 5
