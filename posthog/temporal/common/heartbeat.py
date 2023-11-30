import asyncio
import collections.abc
import datetime as dt
import typing

import temporalio.activity


class AsyncHeartbeatDetails(typing.NamedTuple):
    """Details sent over in a Temporal Activity heartbeat."""

    def make_activity_heartbeat_while_running(
        self, function_to_run: collections.abc.Callable, heartbeat_every: dt.timedelta
    ) -> collections.abc.Callable[..., collections.abc.Coroutine]:
        """Return a callable that returns a coroutine that heartbeats with these HeartbeatDetails.

        The returned callable wraps 'function_to_run' while heartbeating every 'heartbeat_every'
        seconds.
        """

        async def heartbeat() -> None:
            """Heartbeat every 'heartbeat_every' seconds."""
            while True:
                await asyncio.sleep(heartbeat_every.total_seconds())
                temporalio.activity.heartbeat(self)

        async def heartbeat_while_running(*args, **kwargs):
            """Wrap 'function_to_run' to asynchronously heartbeat while awaiting."""
            heartbeat_task = asyncio.create_task(heartbeat())

            try:
                return await function_to_run(*args, **kwargs)
            finally:
                heartbeat_task.cancel()
                await asyncio.wait([heartbeat_task])

        return heartbeat_while_running
