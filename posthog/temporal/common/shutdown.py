import asyncio
import contextvars
import threading
import typing

from temporalio import activity

from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)


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

    @property
    def logger(self):
        """Return a logger with activity context (if available)."""
        try:
            activity_info = activity.info()
        except RuntimeError:
            return LOGGER
        return LOGGER.bind(
            activity_id=activity_info.activity_id,
            activity_type=activity_info.activity_type,
            attempt=activity_info.attempt,
            workflow_type=activity_info.workflow_type,
            workflow_id=activity_info.workflow_id,
            workflow_run_id=activity_info.workflow_run_id,
            workflow_namespace=activity_info.workflow_namespace,
            task_queue=activity_info.task_queue,
        )

    def start(self):
        """Start an `asyncio.Task` to monitor for worker shutdown."""

        async def monitor() -> None:
            self.logger.info("Starting shutdown monitoring task.")

            try:
                await activity.wait_for_worker_shutdown()
            except RuntimeError:
                # Not running in an activity context.
                return

            self._is_shutdown_event.set()

        self._monitor_shutdown_task = asyncio.create_task(monitor())

    def start_sync(self):
        """Start a `threading.Thread` to monitor for worker shutdown.

        Notice we must copy the context to preserve the activity context for the
        monitoring thread.
        """
        context = contextvars.copy_context()

        def monitor() -> None:
            self.logger.info("Starting shutdown monitoring thread.")

            while not self._stop_event_sync.is_set():
                try:
                    activity.wait_for_worker_shutdown_sync(timeout=0.1)
                except RuntimeError:
                    # Not running in an activity context.
                    return
                except Exception:
                    self.logger.exception("An unknown error has occurred in the shutdown monitor thread.")
                    raise

                # Temporal does not return anything from previous call, despite claiming
                # it's a wrapper on `threading.Event.wait`, which does return a `bool`
                # indicating the reason. So we must also check if the event was set.
                if activity.is_worker_shutdown():
                    self.logger.info("Shutdown detected.")
                    self._is_shutdown_event_sync.set()
                    break

        self._monitor_shutdown_thread = threading.Thread(target=context.run, args=(monitor,), daemon=True)
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

    async def wait_for_worker_shutdown(self) -> None:
        """Asynchronously wait for worker shutdown event."""
        _ = await self._is_shutdown_event.wait()

    def wait_for_worker_shutdown_sync(self, timeout: float | None = None) -> bool:
        """Synchronously wait for worker shutdown event."""
        return self._is_shutdown_event_sync.wait(timeout)

    def is_worker_shutdown(self) -> bool:
        """Check if worker is shutting down."""
        return self._is_shutdown_event.is_set() or self._is_shutdown_event_sync.is_set()

    def raise_if_is_worker_shutdown(self):
        """Raise an exception if worker is shutting down."""
        if self.is_worker_shutdown():
            self.logger.debug("Worker is shutting down.")
            raise WorkerShuttingDownError.from_activity_context()

        self.logger.debug("Worker is not shutting down.")
