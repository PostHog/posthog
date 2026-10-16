import asyncio
import threading
from collections.abc import Iterator

import pytest

from parameterized import parameterized

from ee.hogai.utils.asgi import SyncIterableToAsync


class TestSyncIterableToAsync:
    @parameterized.expand([("idle", False), ("reading", True)])
    async def test_closes_cancelled_stream_in_worker(self, _name: str, reading: bool) -> None:
        loop = asyncio.get_running_loop()
        read_started = asyncio.Event()
        close_started = asyncio.Event()
        closed = asyncio.Event()
        release_read = threading.Event()
        release_close = threading.Event()
        closed_on: list[int] = []

        def generate() -> Iterator[int]:
            try:
                yield 1
                loop.call_soon_threadsafe(read_started.set)
                assert release_read.wait(5)
                yield 2
            finally:
                loop.call_soon_threadsafe(close_started.set)
                assert release_close.wait(5)
                closed_on.append(threading.get_ident())
                loop.call_soon_threadsafe(closed.set)

        stream = SyncIterableToAsync(generate())
        assert await anext(stream) == 1
        if reading:
            pending = asyncio.create_task(anext(stream))
            await asyncio.wait_for(read_started.wait(), 5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending

        cleanup = asyncio.create_task(stream.aclose())
        try:
            if reading:
                await asyncio.wait_for(cleanup, 5)
                assert not close_started.is_set()
                release_read.set()
            await asyncio.wait_for(close_started.wait(), 5)
        finally:
            release_read.set()
            release_close.set()
            await asyncio.wait_for(cleanup, 5)
            await asyncio.wait_for(closed.wait(), 5)

        assert len(closed_on) == 1
        assert closed_on[0] != threading.get_ident()
        await stream.aclose()
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
