import asyncio
import typing

from temporalio import activity


class Heartbeater:
    """Regular heartbeatting during Temporal activity execution.

    This class manages two heartbeat tasks via a context manager:
    * A task that hearbeats regularly every 'heartbeat_timeout' / 'factor'.
    * A task that heartbeats after worker shutdown is detected.

    Attributes:
        details: Set this attribute to a tuple to send as heartbeat details.
        factor: Used to determine interval between regular heartbeatting.
        heartbeat_task: A reference to regular heartbeatting task maintained while in the
            context manager to avoid garbage collection.
        heartbeat_on_shutdown_task: A reference to task that heartbeats on shutdown
            maintained while in the context manager to avoid garbage collection.
    """

    def __init__(self, details: tuple[typing.Any, ...] = (), factor: int = 120):
        self._details: tuple[typing.Any, ...] = details
        self.factor = factor
        self.heartbeat_task: asyncio.Task | None = None
        self.heartbeat_on_shutdown_task: asyncio.Task | None = None

    @property
    def details(self) -> tuple[typing.Any, ...]:
        """Return details if available, otherwise an empty tuple."""
        return self._details

    @details.setter
    def details(self, details: tuple[typing.Any, ...]) -> None:
        """Set tuple to be passed as heartbeat details."""
        self._details = details

    async def __aenter__(self):
        """Enter managed heartbeatting context."""

        async def heartbeat_forever(delay: float) -> None:
            """Heartbeat forever every delay seconds."""
            while True:
                await asyncio.sleep(delay)
                activity.heartbeat(*self.details)

        heartbeat_timeout = activity.info().heartbeat_timeout

        if heartbeat_timeout:
            self.heartbeat_task = asyncio.create_task(
                heartbeat_forever(heartbeat_timeout.total_seconds() / self.factor)
            )

        async def heartbeat_on_shutdown() -> None:
            """Handle the Worker shutting down by heart-beating our latest status."""
            await activity.wait_for_worker_shutdown()
            if not self.details:
                return

            activity.heartbeat(*self.details)

        self.heartbeat_on_shutdown_task = asyncio.create_task(heartbeat_on_shutdown())

        return self

    async def __aexit__(self, *args, **kwargs):
        """Cancel heartbeatting tasks on exit."""
        tasks_to_wait = []
        if self.heartbeat_task is not None:
            self.heartbeat_task.cancel()
            tasks_to_wait.append(self.heartbeat_task)

        if self.heartbeat_on_shutdown_task is not None:
            self.heartbeat_on_shutdown_task.cancel()
            tasks_to_wait.append(self.heartbeat_on_shutdown_task)

        if tasks_to_wait:
            await asyncio.wait(tasks_to_wait)

        activity.heartbeat(*self.details)

        self.heartbeat_task = None
        self.heartbeat_on_shutdown_task = None
