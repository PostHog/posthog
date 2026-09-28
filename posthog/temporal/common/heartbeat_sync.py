import time
import socket
import asyncio
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from typing import Any

from structlog import get_logger
from structlog.types import FilteringBoundLogger
from temporalio import activity

from posthog.temporal.common.liveness_tracker import get_liveness_tracker

LOGGER = get_logger(__name__)

# For an async activity, `activity.heartbeat` schedules a task on the event loop. Called from any
# other thread, it fails with "no running event loop" and the server never sees the heartbeat.
_loop_heartbeat: ContextVar[Callable[..., None] | None] = ContextVar("loop_heartbeat", default=None)


@contextmanager
def heartbeat_through_loop(loop: asyncio.AbstractEventLoop) -> Iterator[None]:
    """Make `HeartbeaterSync` send heartbeats through `loop`, for an async activity whose sync body runs on another thread."""
    activity_context = copy_context()

    def heartbeat(*details: Any) -> None:
        loop.call_soon_threadsafe(activity.heartbeat, *details, context=activity_context)

    token = _loop_heartbeat.set(heartbeat)
    try:
        yield
    finally:
        _loop_heartbeat.reset(token)


class HeartbeaterSync:
    def __init__(self, details: tuple[Any, ...] = (), factor: int = 12, logger: FilteringBoundLogger | None = None):
        self.details: tuple[Any, ...] = details
        self.factor = factor
        self.logger = logger or LOGGER.bind()
        self.stop_event: threading.Event | None = None
        self.heartbeat_thread: threading.Thread | None = None

    def log_debug(self, message: str) -> None:
        self.logger.debug(message)

    def heartbeat_regularly(self, stop_event: threading.Event, interval: int, details: tuple[Any, ...]):
        tracker = get_liveness_tracker()
        send_heartbeat = _loop_heartbeat.get() or activity.heartbeat
        while not stop_event.is_set():
            try:
                extra_payload = {"host": socket.gethostname(), "ts": time.time()}
                send_heartbeat(*details, extra_payload)
                tracker.record_heartbeat()
                self.log_debug("Heartbeat")
            except Exception as e:
                self.logger.warning("Heartbeat failed", error=str(e), exc_info=e)
            stop_event.wait(interval)

    def __enter__(self):
        heartbeat_timeout = activity.info().heartbeat_timeout
        if not heartbeat_timeout:
            return

        context = copy_context()
        self.stop_event = threading.Event()

        interval = heartbeat_timeout.total_seconds() / self.factor

        self.log_debug(f"Heartbeat interval: {interval}s")

        self.heartbeat_thread = threading.Thread(
            target=context.run, args=(self.heartbeat_regularly, self.stop_event, interval, self.details), daemon=True
        )

        self.log_debug("Starting heartbeat thread...")
        self.heartbeat_thread.start()

    def __exit__(self, *args, **kwargs):
        if self.stop_event is not None:
            self.stop_event.set()
            self.log_debug("Heartbeat stop event set")

        if self.heartbeat_thread is not None:
            self.heartbeat_thread.join()
            self.log_debug("Heartbeat thread joined")
