from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore, Lock
from typing import TypeVar

from posthog.clickhouse.query_tagging import get_query_tags, query_tags

T = TypeVar("T")
_pool: ThreadPoolExecutor | None = None
_pool_lock = Lock()
_slots = BoundedSemaphore(4)


def _native_metadata_executor() -> tuple[ThreadPoolExecutor, BoundedSemaphore]:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="native_metadata")
        return _pool, _slots


def submit_native_metadata(work: Callable[[], T]) -> Future[T] | None:
    """Bound running and queued native cleanup without making legacy callers wait on it."""
    executor, slots = _native_metadata_executor()
    if not slots.acquire(blocking=False):
        return None

    def release_slot(_future: Future[T]) -> None:
        slots.release()

    try:
        context = copy_context()
        tags = get_query_tags().model_copy()

        def run() -> T:
            query_tags.set(tags)
            return work()

        future = executor.submit(lambda: context.run(run))
    except BaseException:
        slots.release()
        raise
    future.add_done_callback(release_slot)
    return future
