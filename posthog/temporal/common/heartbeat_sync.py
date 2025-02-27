import threading
from typing import Any, Optional
from temporalio import activity
from contextvars import copy_context

from posthog.temporal.common.logger import FilteringBoundLogger


class HeartbeaterSync:
    def __init__(self, details: tuple[Any, ...] = (), factor: int = 12, logger: Optional[FilteringBoundLogger] = None):
        self.details: tuple[Any, ...] = details
        self.factor = factor
        self.logger = logger
        self.stop_event: Optional[threading.Event] = None
        self.heartbeat_thread: Optional[threading.Thread] = None

    def log_debug(self, message: str, exc_info: Optional[Any] = None) -> None:
        if self.logger:
            self.logger.debug(message, exc_info=exc_info)

    def heartbeat_regularly(self, stop_event: threading.Event, interval: int, details: tuple[Any, ...]):
        while not stop_event.is_set():
            try:
                activity.heartbeat(*details)
                self.log_debug("Heartbeat")
            except Exception as e:
                self.log_debug(f"Heartbeat failed {e}", exc_info=e)
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
