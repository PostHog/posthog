import time
import inspect
from collections.abc import Callable, Coroutine
from datetime import datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

from django.conf import settings
from django.db import close_old_connections

from asgiref.sync import sync_to_async
from temporalio import workflow

P = ParamSpec("P")
T = TypeVar("T")


def make_sync_retryable_with_exponential_backoff(
    func: Callable[P, T],
    max_attempts: int = 5,
    initial_retry_delay: float | int = 2,
    max_retry_delay: float | int = 32,
    exponential_backoff_coefficient: int = 2,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    is_exception_retryable: Callable[[Exception], bool] = lambda _: True,
) -> Callable[P, T]:
    """Retry the provided sync `func` until `max_attempts` is reached with exponential backoff."""

    @wraps(func)
    def inner(*args: P.args, **kwargs: P.kwargs) -> T:
        attempt = 0

        while True:
            try:
                return func(*args, **kwargs)
            except retryable_exceptions as err:
                attempt += 1

                if not is_exception_retryable(err) or attempt >= max_attempts:
                    raise

                delay = min(max_retry_delay, initial_retry_delay * (attempt**exponential_backoff_coefficient))
                time.sleep(delay)

    return inner


def asyncify(fn: Callable[P, T]) -> Callable[P, Coroutine[Any, Any, T]]:
    """Decorator to convert a sync function using sync_to_async - this preserves type hints for Temporal's serialization while allowing sync Django ORM code.

    This preserves type hints for Temporal's serialization while allowing
    sync Django ORM code.

    Usage:
        @activity.defn
        @asyncify
        def my_activity(task_id: str) -> TaskDetails:
            task = Task.objects.get(id=task_id)
            return TaskDetails(...)
    """
    if inspect.iscoroutinefunction(fn):
        raise TypeError(
            f"@asyncify should only be used on sync functions. '{fn.__name__}' is already async. Remove @asyncify."
        )

    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        return await sync_to_async(fn)(*args, **kwargs)

    return wrapper


def _close_db_connections() -> None:
    """Close old database connections to prevent usage of stale connections in long-running Temporal workers."""
    if not settings.TEST:
        close_old_connections()


def close_db_connections(fn: Callable[P, T]) -> Callable[P, T]:
    """Decorator that evicts stale Django DB connections around an activity.

    Long-running Temporal workers don't go through Django's request cycle, so the
    ``request_started`` / ``request_finished`` signals that normally call
    ``close_old_connections()`` never fire. Connections that have exceeded
    ``CONN_MAX_AGE`` or been killed by the database stay in the pool until the
    next query fails. Apply this decorator to activities that touch the Django
    ORM directly to mirror the request-cycle behaviour.

    Skipped under ``settings.TEST`` to avoid tearing down the test DB connection
    that ``transaction=True`` fixtures rely on.

    Stack below ``@activity.defn``. For sync activities wrapped in ``@asyncify``,
    place ``@close_db_connections`` *innermost* so connection cleanup runs on the
    same ``sync_to_async`` thread as the ORM work::

        @activity.defn
        @close_db_connections
        async def my_activity(...): ...

        @activity.defn
        @asyncify
        @close_db_connections
        def my_sync_activity(...): ...
    """
    if inspect.iscoroutinefunction(fn):

        @wraps(fn)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            await sync_to_async(_close_db_connections)()
            try:
                return await fn(*args, **kwargs)
            finally:
                await sync_to_async(_close_db_connections)()

        return cast(Callable[P, T], async_wrapper)

    @wraps(fn)
    def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        _close_db_connections()
        try:
            return fn(*args, **kwargs)
        finally:
            _close_db_connections()

    return sync_wrapper


def get_scheduled_start_time():
    """Return the start time of a workflow.

    Raises:
        TypeError: If when trying to obtain the data interval end we run into non-str types.

    Returns:
        A datetime indicating the start time of the workflow.
    """
    scheduled_start_time_attr = workflow.info().search_attributes.get("TemporalScheduledStartTime")

    # These two if-checks are a bit pedantic, but Temporal SDK is heavily typed.
    # So, they exist to make mypy happy.
    if scheduled_start_time_attr is None:
        msg = (
            "Expected 'TemporalScheduledStartTime' of type 'list[str]' or 'list[datetime]', found 'NoneType'."
            "This should be set by the Temporal Schedule unless triggering workflow manually."
        )
        raise TypeError(msg)

    # Failing here would perhaps be a bug in Temporal.
    if isinstance(scheduled_start_time_attr[0], str):
        scheduled_start_time_str = scheduled_start_time_attr[0]
        return datetime.fromisoformat(scheduled_start_time_str)

    elif isinstance(scheduled_start_time_attr[0], datetime):
        return scheduled_start_time_attr[0]

    else:
        msg = (
            f"Expected search attribute to be of type 'str' or 'datetime' but found '{scheduled_start_time_attr[0]}' "
            f"of type '{type(scheduled_start_time_attr[0])}'."
        )
        raise TypeError(msg)
