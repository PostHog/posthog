import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore
from typing import cast

from django.db import connections

from rest_framework.exceptions import APIException

from posthog.models.scoping import team_scope

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="context-request")
_CAPACITY = BoundedSemaphore(4)


class SelectionUnavailable(APIException):
    status_code = 503
    default_detail = "Context selection is busy or exceeded its request deadline."


def bounded_request[T](team_id: int, seconds: float, operation: Callable[[float], T]) -> T:
    deadline = time.monotonic() + seconds
    if not _CAPACITY.acquire(blocking=False):
        raise SelectionUnavailable()

    def run() -> T:
        try:
            with team_scope(team_id):
                return operation(deadline)
        finally:
            connections.close_all()

    # A timed-out DB/cache call cannot be killed safely. Keep its slot occupied until it exits,
    # so dependency failure cannot accumulate orphaned work or an unbounded queue.
    try:
        future = _EXECUTOR.submit(copy_context().run, run)
    except Exception:
        _CAPACITY.release()
        raise
    future.add_done_callback(lambda _: _CAPACITY.release())
    try:
        return cast(T, future.result(timeout=max(0, deadline - time.monotonic())))
    except TimeoutError as error:
        future.cancel()
        raise SelectionUnavailable() from error
