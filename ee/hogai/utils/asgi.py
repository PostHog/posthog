import threading
from collections.abc import AsyncIterator, Iterable, Iterator
from typing import TypeVar

from asgiref.sync import sync_to_async

T = TypeVar("T")


class SyncIterableToAsync(AsyncIterator[T]):
    def __init__(self, iterable: Iterable[T]) -> None:
        self._iterable: Iterable[T] = iterable
        self.sync_iterator: Iterator[T] | None = None
        self._lock = threading.Lock()
        self._closed = False

    def __aiter__(self) -> AsyncIterator[T]:
        return self

    async def __anext__(self) -> T:
        return await sync_to_async(self._next, thread_sensitive=False)()

    def _next(self) -> T:
        with self._lock:
            if self._closed:
                raise StopAsyncIteration
            if self.sync_iterator is None:
                self.sync_iterator = iter(self._iterable)
            return self.next(self.sync_iterator)

    def _close(self) -> None:
        # Cancellation stops the await but not the worker, so closing must wait for an in-flight next().
        with self._lock:
            if self._closed:
                return
            self._closed = True
            iterator = self.sync_iterator if self.sync_iterator is not None else self._iterable
            close = getattr(iterator, "close", None)
            if close is not None:
                close()

    async def aclose(self) -> None:
        await sync_to_async(self._close, thread_sensitive=False)()

    @staticmethod
    def next(it: Iterator[T]) -> T:
        """
        asyncio expects `StopAsyncIteration` in place of `StopIteration`,
        so here's a modified in-built `next` function that can handle this.
        """
        try:
            return next(it)
        except StopIteration:
            raise StopAsyncIteration
