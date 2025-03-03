import asyncio
import threading
import typing

from temporalio import activity


class WorkerShuttingDownError(Exception):
    """Exception raised when a worker shutdown was issued.

    In general, this should always be retried.
    """

    def __init__(
        self, activity_id: str, activity_type: str, task_queue: str, attempt: int, workflow_id: str, workflow_type: str
    ):
        self.activity_id = activity_id
        self.activity_type = activity_type
        self.attempt = attempt
        self.task_queue = task_queue
        self.workflow_id = workflow_id
        self.workflow_type = workflow_type

        super().__init__(
            f"The activity <{activity_type}: {activity_id}> "
            + f"from workflow <{workflow_type}: {workflow_id}> "
            + f"on attempt number {attempt} from task queue '{task_queue}'"
            + " is running on a worker that is shutting down"
        )

    @classmethod
    def from_activity_context(cls) -> typing.Self:
        """Initialize this exception from within an activity context."""
        info = activity.info()
        return cls(
            info.activity_id, info.activity_type, info.task_queue, info.attempt, info.workflow_id, info.workflow_type
        )


class ShutdownMonitor:
    """Monitor for Temporal worker graceful shutdown.

    Handling shutdown is cooperative: We expect users of `ShutdownMonitor` to
    actively check for shutdown by calling `is_worker_shutdown` or
    `raise_if_is_worker_shutdown`.

    All Temporal activities should consider `WorkerShuttingDownError` as a
    retryable exception, at least if they wish to have new workers pick it up.
    """

    def __init__(self):
        self._monitor_shutdown_task: asyncio.Task[None] | None = None
        self._monitor_shutdown_thread: threading.Thread | None = None
        self._is_shutdown_event = asyncio.Event()
        self._is_shutdown_event_sync = threading.Event()
        self._stop_event_sync = threading.Event()

    def __str__(self) -> str:
        """Return a string representation of this `ShutdownMonitor`."""
        if not self._monitor_shutdown_task and not self._monitor_shutdown_thread:
            return f"<ShutdownMonitor: Not started>"

        if self.is_worker_shutdown():
            return f"<ShutdownMonitor: Worker shutting down>"
        else:
            return f"<ShutdownMonitor: Worker running>"

    def start(self):
        """Start an `asyncio.Task` to monitor for worker shutdown."""

        async def monitor() -> None:
            await activity.wait_for_worker_shutdown()
            self._is_shutdown_event.set()

        self._monitor_shutdown_task = asyncio.create_task(monitor())

    def start_sync(self):
        """Start a `threading.Thread` to monitor for worker shutdown."""

        def monitor() -> None:
            while not self._stop_event_sync.is_set():
                try:
                    activity.wait_for_worker_shutdown_sync(timeout=1.0)
                except TimeoutError:
                    continue
                else:
                    self._is_shutdown_event_sync.set()
                    break

        self._monitor_shutdown_thread = threading.Thread(target=monitor, daemon=True)
        self._monitor_shutdown_thread.start()

    def stop(self):
        """Cancel pending monitoring `asyncio.Task`."""
        if self._monitor_shutdown_task and not self._monitor_shutdown_task.done():
            _ = self._monitor_shutdown_task.cancel()
            self._monitor_shutdown_task = None

    def stop_sync(self):
        """Cancel pending monitoring `threading.Thread`."""
        if self._monitor_shutdown_thread:
            self._stop_event_sync.set()
            self._monitor_shutdown_thread.join()
            self._monitor_shutdown_thread = None

    async def __aenter__(self) -> typing.Self:
        """Async context manager that manages monitoring task within context."""
        self.start()
        return self

    async def __aexit__(self, *args, **kwargs):
        """Stop pending any pending monitoring tasks on context manager exit."""
        self.stop()

    def __enter__(self) -> typing.Self:
        """Context manager that manages monitoring thread within context."""
        self.start_sync()
        return self

    def __exit__(self, *args, **kwargs):
        """Stop pending any pending monitoring threads on context manager exit."""
        self.stop_sync()

    def is_worker_shutdown(self) -> bool:
        """Check if worker is shutting down."""
        return self._is_shutdown_event.is_set() or self._is_shutdown_event_sync.is_set()

    def raise_if_is_worker_shutdown(self):
        """Raise an exception if worker is shutting down."""
        if self.is_worker_shutdown():
            raise WorkerShuttingDownError.from_activity_context()
