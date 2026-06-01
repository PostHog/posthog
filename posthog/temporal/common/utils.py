import time
import inspect
import threading
from collections.abc import Callable, Coroutine
from datetime import datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

import django.db
from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity, workflow

from posthog.exceptions_capture import capture_exception

P = ParamSpec("P")
T = TypeVar("T")

logger = structlog.get_logger(__name__)


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
        submit_time = time.monotonic()

        def instrumented() -> T:
            start_time = time.monotonic()
            try:
                return fn(*args, **kwargs)
            finally:
                now = time.monotonic()
                thread_wait = start_time - submit_time
                execution_time = now - start_time
                if activity.in_activity():
                    activity.logger.warning(
                        "asyncify_slow",
                        extra={
                            "function": fn.__name__,
                            "thread_wait_seconds": round(thread_wait, 3),
                            "execution_seconds": round(execution_time, 3),
                            "thread_name": threading.current_thread().name,
                            "activity_id": activity.info().activity_id,
                        },
                    )

        return await sync_to_async(thread_sensitive=False)(close_db_connections(instrumented))()

    return wrapper


def _close_initialized_connections() -> None:
    for conn in django.db.connections.all(initialized_only=True):
        conn.close()


def recycle_db_connections() -> None:
    """Hard-close this thread's initialized Django connections (skipped under TEST).

    Stronger than ``close_old_connections()``: that only evicts connections Django
    deems obsolete or unusable, so a connection pinned to a now-read-only Postgres
    replica (after an Aurora failover or pgbouncer reroute) survives — it still
    answers ``SELECT 1`` and reads succeed. This closes unconditionally so the next
    query dials a fresh, writable connection. Call it in the same thread that holds
    the stale handle (Django connections are thread-local).

    Skipped under ``settings.TEST`` to avoid tearing down the test DB connection
    that ``transaction=True`` fixtures rely on.
    """
    if not settings.TEST:
        _close_initialized_connections()


# Read-only SQL transaction (PostgreSQL SQLSTATE 25006). psycopg raises
# ``ReadOnlySqlTransaction`` with this code; Django re-wraps it as
# ``django.db.utils.InternalError``, keeping the original as ``__cause__``.
_READ_ONLY_SQL_TRANSACTION_SQLSTATE = "25006"


def is_read_only_connection_error(exc: BaseException) -> bool:
    """True when ``exc`` was raised because the current connection points at a
    read-only Postgres host — typically a long-lived Temporal worker connection
    left pinned to a replica after a failover or pgbouncer reroute.

    Walks the exception chain so it matches both the raw psycopg error and the
    ``django.db.utils.InternalError`` Django wraps it in, falling back to the
    message when the SQLSTATE isn't carried through.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "sqlstate", None) == _READ_ONLY_SQL_TRANSACTION_SQLSTATE:
            return True
        current = current.__cause__ or current.__context__
    return "read-only transaction" in str(exc).lower()


def retry_once_on_read_only_connection(fn: Callable[P, T]) -> Callable[P, T]:
    """Wrap a SYNC DB callable so a read-only-connection failure recycles this
    thread's connections and retries the call once on a fresh, writable connection.

    Must wrap the callable that runs the ORM write itself: the connection close has
    to happen in the same worker thread that holds the stale handle. Wrapping an
    async activity that delegates its writes to a thread pool (e.g. via
    ``database_sync_to_async``) would close the wrong thread's connections and not
    help. The wrapped call must be safe to run twice (the first attempt's
    transaction never committed).
    """
    if inspect.iscoroutinefunction(fn):
        raise TypeError(
            f"retry_once_on_read_only_connection wraps sync DB callables; '{fn.__name__}' is async. "
            "Apply it to the sync function that runs inside the worker thread."
        )

    @wraps(fn)
    def inner(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if not is_read_only_connection_error(exc):
                raise
            # Surface the failover: a silent recovery would make a stale-replica
            # event invisible (the call looks like it just succeeded).
            logger.warning(
                "Recycling read-only DB connection and retrying once",
                function=fn.__name__,
                error=str(exc),
            )
            capture_exception(exc, {"function": fn.__name__, "recovery": "read_only_connection_retry"})
            recycle_db_connections()
            return fn(*args, **kwargs)

    return inner


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

    Stack below ``@activity.defn``. Asyncified activities should use the ``@asyncify`` decorator instead,
    which preserves type hints for Temporal's serialization while allowing sync Django ORM code.
        @activity.defn
        @close_db_connections
        async def my_activity(...): ...
    """
    if inspect.iscoroutinefunction(fn):

        @wraps(fn)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            await sync_to_async(recycle_db_connections)()
            try:
                return await fn(*args, **kwargs)
            finally:
                await sync_to_async(recycle_db_connections)()

        return cast(Callable[P, T], async_wrapper)

    @wraps(fn)
    def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        recycle_db_connections()
        try:
            return fn(*args, **kwargs)
        finally:
            recycle_db_connections()

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
