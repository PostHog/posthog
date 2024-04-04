import asyncio
import typing

from temporalio import activity


class Heartbeatter:
    def __init__(self, details: None | tuple[typing.Any, ...] = None, factor: int = 2):
        self._details: None | tuple[typing.Any, ...] = details
        self.factor = factor
        self.heartbeat_task: asyncio.Task | None = None
        self.heartbeat_on_shutdown_task: asyncio.Task | None = None

    @property
    def details(self) -> tuple[typing.Any, ...]:
        if self._details is None:
            return ()
        return self._details

    @details.setter
    def details(self, details: tuple[typing.Any, ...]) -> None:
        self._details = details

    async def __aenter__(self):
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
        if self.heartbeat_task:
            self.heartbeat_task.cancel()

            await asyncio.wait([self.heartbeat_task])

            self.heartbeat_task = None

        if self.heartbeat_on_shutdown_task:
            self.heartbeat_on_shutdown_task.cancel()

            await asyncio.wait([self.heartbeat_on_shutdown_task])

            self.heartbeat_task = None
