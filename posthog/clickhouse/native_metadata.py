from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore, Lock
from typing import TypeVar

from django.db import connections

from posthog.clickhouse.query_tagging import get_query_tags, query_tags

T = TypeVar("T")
_pool: ThreadPoolExecutor | None = None
_pool_lock = Lock()
_slots = BoundedSemaphore(4)
_legacy_pool: ThreadPoolExecutor | None = None
_legacy_slots = BoundedSemaphore(1)


def _native_metadata_executor() -> tuple[ThreadPoolExecutor, BoundedSemaphore]:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="native_metadata")
        return _pool, _slots


def submit_native_metadata(work: Callable[[], T]) -> Future[T] | None:
    return _submit_metadata(work, *_native_metadata_executor())


def submit_legacy_metadata(work: Callable[[], T]) -> Future[T] | None:
    global _legacy_pool
    # A stalled legacy probe must not consume the native cluster's cleanup capacity.
    with _pool_lock:
        if _legacy_pool is None:
            _legacy_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="legacy_metadata")
        executor = _legacy_pool
    return _submit_metadata(work, executor, _legacy_slots)


def _submit_metadata(work: Callable[[], T], executor: ThreadPoolExecutor, slots: BoundedSemaphore) -> Future[T] | None:
    if not slots.acquire(blocking=False):
        return None

    def release_slot(_future: Future[T]) -> None:
        slots.release()

    try:
        context = copy_context()
        tags = get_query_tags().model_copy()

        def run() -> T:
            query_tags.set(tags)
            try:
                return work()
            finally:
                connections.close_all()

        future = executor.submit(lambda: context.run(run))
    except BaseException:
        slots.release()
        raise
    future.add_done_callback(release_slot)
    return future
