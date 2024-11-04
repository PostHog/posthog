import threading
from typing import Any
from temporalio import activity


class HeartbeaterSync:
    def __init__(self, details: tuple[Any, ...] = (), factor: int = 12):
        self.details: tuple[Any, ...] = details
        self.factor = factor

    def heartbeat_regularly(self, stop_event: threading.Event, interval: int, details: tuple[Any, ...]):
        while not stop_event.is_set():
            activity.heartbeat(*details)
            stop_event.wait(interval)

    def __enter__(self):
        heartbeat_timeout = activity.info().heartbeat_timeout
        if not heartbeat_timeout:
            return

        self.stop_event = threading.Event()

        interval = heartbeat_timeout.total_seconds() / self.factor

        self.heartbeat_thread = threading.Thread(
            target=self.heartbeat_regularly, args=(self.stop_event, interval, self.details), daemon=True
        )
        self.heartbeat_thread.start()

    def __exit__(self, *args, **kwargs):
        if self.stop_event is not None:
            self.stop_event.set()

        if self.heartbeat_thread is not None:
            self.heartbeat_thread.join()
