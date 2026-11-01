import uuid
import random
import typing
import asyncio
import functools
import contextlib
import collections.abc

from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.models.batch_export import BatchExportRun
from products.batch_exports.backend.service import aupdate_batch_export_run
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult

T = typing.TypeVar("T")
LOGGER = get_write_only_logger(__name__)


def peek_first_and_rewind(
    gen: collections.abc.Generator[T],
) -> tuple[T | None, collections.abc.Generator[T]]:
    """Peek into the first element in a generator and rewind the advance.

    The generator is advanced and cannot be reversed, so we create a new one that first
    yields the element we popped before yielding the rest of the generator.

    Returns:
        A tuple with the first element of the generator and the generator itself.
    """
    try:
        first = next(gen)
    except StopIteration:
        first = None

    def rewind_gen() -> collections.abc.Generator[T]:
        """Yield the item we popped to rewind the generator.

        Return early if the generator is empty.
        """
        if first is None:
            return

        yield first
        yield from gen

    return (first, rewind_gen())


async def apeek_first_and_rewind(
    gen: collections.abc.AsyncGenerator[T],
) -> tuple[T | None, collections.abc.AsyncGenerator[T]]:
    """Peek into the first element in a generator and rewind the advance.

    The generator is advanced and cannot be reversed, so we create a new one that first
    yields the element we popped before yielding the rest of the generator.

    Returns:
        A tuple with the first element of the generator and the generator itself.
    """
    try:
        first = await anext(gen)
    except StopAsyncIteration:
        first = None

    async def rewind_gen() -> collections.abc.AsyncGenerator[T]:
        """Yield the item we popped to rewind the generator.

        Return early if the generator is empty.
        """
        if first is None:
            return

        yield first

        async for value in gen:
            yield value

    return (first, rewind_gen())


@contextlib.asynccontextmanager
async def set_status_to_running_task(run_id: str | None) -> collections.abc.AsyncGenerator[asyncio.Task | None]:
    """Manage a background task to set a batch export run status to 'RUNNING'.

    This is intended to be used within a batch export's 'insert_*' activity. These activities cannot afford
    to fail if our database is experiencing issues, as we should strive to not let issues in our infrastructure
    propagate to users. So, we do a best effort update and swallow the exception if we fail.

    Even if we fail to update the status here, the 'finish_batch_export_run' activity at the end of each batch
    export will retry indefinitely and wait for postgres to recover, eventually making a final update with
    the status. This means that, worse case, the batch export status won't be displayed as 'RUNNING' while running.
    """
    if run_id is None:
        # Should never land here except in tests of individual activities
        yield None
        return

    background_task = asyncio.create_task(
        aupdate_batch_export_run(uuid.UUID(run_id), status=BatchExportRun.Status.RUNNING)
    )

    def done_callback(task):
        if task.exception() is not None:
            LOGGER.warning(
                "Unexpected error trying to set batch export to 'RUNNING' status. Run will continue but displayed status may not be accurate until run finishes",
                exc_info=task.exception(),
            )

    background_task.add_done_callback(done_callback)

    try:
        yield background_task
    finally:
        if not background_task.done():
            background_task.cancel()
            await asyncio.wait([background_task])


_Result = typing.TypeVar("_Result")
FutureLike = (
    asyncio.Future[_Result] | collections.abc.Coroutine[None, typing.Any, _Result] | collections.abc.Awaitable[_Result]
)


_P = typing.ParamSpec("_P")


def make_retryable_with_exponential_backoff(
    func: typing.Callable[_P, collections.abc.Awaitable[_Result]],
    timeout: float | int | None = None,
    max_attempts: int | None = 5,
    initial_retry_delay: float | int = 2,
    max_retry_delay: float | int = 32,
    exponential_backoff_coefficient: int = 2,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    is_exception_retryable: typing.Callable[[Exception], bool] = lambda _: True,
    max_delay_jitter: int | float = 3,
) -> typing.Callable[_P, collections.abc.Coroutine[typing.Any, typing.Any, _Result]]:
    """Retry the provided async `func` until `max_attempts` is reached.

    All units are in seconds.

    Arguments:
        func: The coroutine to retry.
        timeout: How long to wait for the coroutine to run.
        max_attempts: Limit number of retry attempts. Set to `None` for no limit.
        initial_retry_delay: Delay for the first retry.
        max_retry_delay: Maximum possible delay between any attempts.
        exponential_backoff_coefficient: Exponential factor used to scale
            `initial_retry_delay`.
        retryable_exceptions: Tuple of exceptions that should be retried. Anything else
            will be re-raised.
        is_exception_retryable: Function called with a caught exception to further
            determine whether it can be retried or not. This is useful for when, for
            example, the same exception class can be retried or not depending on a code
            or message attribute.
        max_delay_jitter: Maximum jitter added to every retry delay.

    Examples:
        Retry an error forever:

        >>> class MyError(Exception):
        ...     pass
        >>> async def my_coro():
        ...     raise MyError
        >>> retryable_coro = make_retryable_with_exponential_backoff(my_coro, max_attempts=None, retryable_exceptions=(MyError,))

        Filter which errors to retry on based on message contents:

        >>> def _is_exception_retryable(exc: Exception):
        ...     return "message" in str(exc)
        >>> retryable_coro = make_retryable_with_exponential_backoff(my_coro, is_exception_retryable=_is_exception_retryable)
    """

    @functools.wraps(func)
    async def inner(*args: _P.args, **kwargs: _P.kwargs) -> _Result:
        attempt = 0

        while True:
            try:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)

            except retryable_exceptions as err:
                attempt += 1

                if is_exception_retryable(err) is False or (max_attempts is not None and attempt >= max_attempts):
                    raise

                await asyncio.sleep(
                    min(max_retry_delay, initial_retry_delay * (attempt**exponential_backoff_coefficient))
                    + random.uniform(0, max_delay_jitter)
                )

            else:
                return result

    return inner


def handle_non_retryable_errors(non_retryable_error_types: typing.Sequence[str]):
    """Decorator to handle non-retryable errors in batch export activities.

    This decorator wraps batch export activities to catch exceptions and determine
    whether they are:
    a) an internal error and should be retried (by allowing the activity to fail) or
    b) a user error and should be returned as a BatchExportResult with an error.

    For now, we just take in a list of error class names that should not be retried.
    In the future, we should use actual exception classes instead of strings.

    Args:
        non_retryable_error_types: List of error class names that should not be retried.

    Returns:
        A decorator function that handles exceptions according to the retry policy.

    Example:
        @activity.defn
        @handle_non_retryable_errors(("ClientError", "ParamValidationError"))
        async def insert_into_s3_activity(inputs: S3InsertInputs) -> BatchExportResult:
            # Activity implementation here
            return BatchExportResult(records_completed=100)
    """

    def decorator(func: typing.Callable[..., collections.abc.Awaitable[BatchExportResult]]):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> BatchExportResult:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                # If we catch an error at any point during this activity, we check if it's a non-retryable error.
                # If it is, we return a BatchExportResult with the error.
                # If it's not, we re-raise the error.
                # TODO: Use actual exception classes instead of strings.
                if e.__class__.__name__ in non_retryable_error_types:
                    LOGGER.exception("Non-retryable error caught in activity")
                    return BatchExportResult.from_exception(e)
                LOGGER.exception("Retryable error caught in activity")
                raise

        return wrapper

    return decorator
