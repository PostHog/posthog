import signal
import typing
import asyncio
import threading
import contextvars
from collections.abc import Callable

from structlog import get_logger
from temporalio import activity

LOGGER = get_logger(__name__)


class WorkerShuttingDownError(Exception):
    """Exception raised when a worker shutdown was issued.

    In general, this should always be retried.
    """

    def __init__(
        self,
        activity_id: str,
        activity_type: str,
        task_queue: str,
        attempt: int,
        workflow_id: str | None,
        workflow_type: str | None,
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
        self._on_shutdown_callbacks: list[tuple[contextvars.Context, Callable[[], None]]] = []
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

            self.logger.info("Shutdown detected.")
            # Run the callbacks before the event is set: a caller that sees the event can raise and
            # leave the monitor at once, and a callback that ran after that would never run at all.
            for context, callback in self._on_shutdown_callbacks:
                try:
                    context.run(callback)
                except Exception:
                    self.logger.exception("A shutdown callback failed.")
            self._is_shutdown_event.set()

        self._monitor_shutdown_task = asyncio.create_task(monitor())

    def run_on_shutdown(self, callback: Callable[[], None]) -> None:
        """Call `callback` once when the worker starts to shut down.

        `callback` runs with a copy of the caller's contextvars, taken now, so it sees the structlog
        context the caller has bound (for example the job context an activity binds after it enters
        the monitor). Only the async monitor calls it, so register it inside `async with ShutdownMonitor()`.
        """
        self._on_shutdown_callbacks.append((contextvars.copy_context(), callback))

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


class ShutdownSignalListener:
    """Record SIGTERM and SIGINT for a worker to act on, without depending on asyncio's self-pipe.

    `loop.add_signal_handler` delivers a signal through a wakeup byte that the C signal handler
    writes to the loop's self-pipe. When that pipe is full, the write fails with `BlockingIOError`
    ("Exception ignored when trying to write to the signal wakeup fd"), the byte is lost, and the
    worker never starts to shut down. It then keeps polling for new work until the pod is killed.

    A Python-level handler from `signal.signal` runs in the main thread whether or not the byte
    reaches the pipe, so this listener records the signal there and `wait` polls for it.
    """

    def __init__(
        self,
        signals: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT),
        poll_interval_seconds: float = 1.0,
    ):
        self._signals = signals
        self._poll_interval_seconds = poll_interval_seconds
        self._received: signal.Signals | None = None
        self._received_event = threading.Event()

    def install(self) -> None:
        """Replace the handlers for the listened signals. Call it from the main thread."""
        for sig in self._signals:
            signal.signal(sig, self._handle)

    def _handle(self, signum: int, frame: object) -> None:
        # A later signal (for example the SIGTERM that the worker wrapper script sends again) keeps
        # the first one, so a shutdown starts only once.
        if self._received is None:
            self._received = signal.Signals(signum)
        self._received_event.set()

    @property
    def received(self) -> signal.Signals | None:
        return self._received

    async def wait(self) -> signal.Signals:
        """Return the first signal received, polling so that no wakeup byte is needed."""
        while not self._received_event.is_set():
            await asyncio.sleep(self._poll_interval_seconds)
        assert self._received is not None
        return self._received
