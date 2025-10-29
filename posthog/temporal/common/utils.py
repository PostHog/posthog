import time
import inspect
from collections.abc import Callable, Coroutine
from datetime import datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar

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
            f"@asyncify should only be used on sync functions. " f"'{fn.__name__}' is already async. Remove @asyncify."
        )

    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        return await sync_to_async(fn)(*args, **kwargs)

    return wrapper


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
