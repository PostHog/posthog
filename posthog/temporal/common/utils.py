import time
import inspect
import threading
from collections.abc import Callable, Coroutine
from datetime import datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

import django.db
from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio import activity, workflow

P = ParamSpec("P")
T = TypeVar("T")


def close_stale_db_connections() -> None:
    """Close expired or errored Postgres connections accumulated by long-lived worker threads.

    Unlike django.db.close_old_connections, skips connections inside an atomic block, so it is
    safe to call from activities running under test transactions.
    """
    for conn in django.db.connections.all(initialized_only=True):
        if not conn.in_atomic_block:
            conn.close_if_unusable_or_obsolete()


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


def _close_db_connections() -> None:
    """Close old database connections to prevent usage of stale connections in long-running Temporal workers."""
    if not settings.TEST:
        _close_initialized_connections()


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


# The wording Postgres uses for SQLSTATE 25006, and the class name Django reports it under. Temporal
# renders a wrapped activity failure as ``<ExceptionClass>: <message>``, so the prefix is how this
# error identifies itself to code that only sees the flattened string across a workflow boundary.
READ_ONLY_TRANSACTION_PHRASE = "read-only transaction"
APP_DB_ERROR_PREFIX = f"{django.db.InternalError.__name__}:".lower()


def is_stale_connection_read_only_error(error: Exception) -> bool:
    """Whether `error` is a write rejected because the connection outlived a primary failover.

    A connection held open across a Postgres failover/switchover keeps talking to what is now a
    demoted standby (or a pooler backend still routed there mid-cutover), so any write on it fails
    with ``cannot execute ... in a read-only transaction`` (``psycopg.errors.ReadOnlySqlTransaction``,
    surfaced by Django as ``InternalError``). This is the same stale-pooled-connection failure mode
    ``OperationalError``/``InterfaceError`` already cover, just a different DB-API exception class —
    closing the connection and retrying reconnects to the current primary.
    """
    return isinstance(error, django.db.InternalError) and READ_ONLY_TRANSACTION_PHRASE in str(error).lower()


async def aretry_on_db_connection_drop(operation: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run an async DB operation, retrying once on a transient connection drop.

    Long-lived Temporal workers pool their connections through pgbouncer, so a pool
    recycle, failover, or deploy can leave a stale pooled connection that raises
    ``OperationalError`` / ``InterfaceError`` the first time it's used — or, for a write,
    ``InternalError`` if the stale connection now points at a demoted standby (see
    ``is_stale_connection_read_only_error``). Evict the dead connection and retry once, so a
    transient blip at an activity's early connect-time reads succeeds on a fresh connection
    instead of escaping as error-tracking noise. A second failure propagates — that's a
    genuinely degraded DB, left to the caller's retry posture.

    Pass a zero-arg callable that *produces* the awaitable (not the awaitable itself),
    so the retry can issue a fresh query:

        team = await aretry_on_db_connection_drop(lambda: Team.objects.aget(pk=team_id))
    """
    try:
        return await operation()
    except django.db.InternalError as e:
        if not is_stale_connection_read_only_error(e):
            raise
        await sync_to_async(_close_db_connections)()
        return await operation()
    except (django.db.OperationalError, django.db.InterfaceError):
        await sync_to_async(_close_db_connections)()
        return await operation()


def retry_on_db_connection_drop(operation: Callable[[], T]) -> T:
    """Run a sync DB operation, retrying once on a transient connection drop.

    The sync sibling of ``aretry_on_db_connection_drop``, for activities that run sync
    Django ORM code (e.g. under ``@asyncify``). See that function for the full rationale:
    a long-lived worker pools connections through pgbouncer, so a pool recycle / failover
    / deploy can leave a stale pooled connection that raises ``OperationalError`` /
    ``InterfaceError`` on first use — or, for a write, ``InternalError`` if the stale
    connection now points at a demoted standby (see ``is_stale_connection_read_only_error``).
    Evict the dead connection and retry once; a second failure propagates, left to the
    caller's retry posture.

    The single retry leans on the activity's outer Temporal retry policy. Code without
    one (e.g. a Celery task) needs multi-attempt backoff instead; see
    ``posthog.storage.hypercache_verifier._fetch_team_batch``.

    Pass a zero-arg callable that *produces* the result, so the retry can issue a fresh
    query:

        task = retry_on_db_connection_drop(lambda: Task.objects.get(id=task_id))
    """
    try:
        return operation()
    except django.db.InternalError as e:
        if not is_stale_connection_read_only_error(e):
            raise
        _close_db_connections()
        return operation()
    except (django.db.OperationalError, django.db.InterfaceError):
        _close_db_connections()
        return operation()


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
