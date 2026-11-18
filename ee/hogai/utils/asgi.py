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
        self._close_requested = threading.Event()
        self._closed = False

    def __aiter__(self) -> AsyncIterator[T]:
        return self

    async def __anext__(self) -> T:
        return await sync_to_async(self._next, thread_sensitive=False)()

    def _next(self) -> T:
        try:
            with self._lock:
                if self._close_requested.is_set():
                    raise StopAsyncIteration
                if self.sync_iterator is None:
                    self.sync_iterator = iter(self._iterable)
                return self.next(self.sync_iterator)
        finally:
            if self._close_requested.is_set():
                self._close()

    def _close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            iterator = self.sync_iterator if self.sync_iterator is not None else self._iterable
            close = getattr(iterator, "close", None)
            if close is not None:
                close()

    async def aclose(self) -> None:
        self._close_requested.set()
        # Cancellation cannot interrupt a sync read, so its worker closes the iterator when the read finishes.
        if self._lock.acquire(blocking=False):
            self._lock.release()
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
