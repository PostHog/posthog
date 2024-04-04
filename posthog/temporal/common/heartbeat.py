import asyncio
import collections.abc
import contextlib
import typing

from temporalio import activity


def no_details() -> tuple:
    """No heartbeat details."""
    return ()


@contextlib.asynccontextmanager
async def heartbeat_every(
    factor: int = 2,
    details_callable: collections.abc.Callable[[], tuple[typing.Any, ...]] = no_details,
) -> collections.abc.AsyncIterator[None]:
    """Heartbeat every Activity heartbeat timeout / factor seconds while in context."""
    heartbeat_timeout = activity.info().heartbeat_timeout
    heartbeat_task = None

    async def heartbeat_forever(delay: float) -> None:
        """Heartbeat forever every delay seconds."""
        while True:
            await asyncio.sleep(delay)
            activity.heartbeat(*details_callable())

    if heartbeat_timeout:
        heartbeat_task = asyncio.create_task(heartbeat_forever(heartbeat_timeout.total_seconds() / factor))

    try:
        yield
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
            await asyncio.wait([heartbeat_task])
