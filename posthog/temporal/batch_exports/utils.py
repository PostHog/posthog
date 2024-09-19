import asyncio
import collections.abc
import contextlib
import functools
import typing
import uuid

import orjson
import pyarrow as pa
import structlog

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import aupdate_batch_export_run

T = typing.TypeVar("T")
logger = structlog.get_logger()


def peek_first_and_rewind(
    gen: collections.abc.Generator[T, None, None],
) -> tuple[T | None, collections.abc.Generator[T, None, None]]:
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

    def rewind_gen() -> collections.abc.Generator[T, None, None]:
        """Yield the item we popped to rewind the generator.

        Return early if the generator is empty.
        """
        if first is None:
            return

        yield first
        yield from gen

    return (first, rewind_gen())


async def apeek_first_and_rewind(
    gen: collections.abc.AsyncGenerator[T, None],
) -> tuple[T | None, collections.abc.AsyncGenerator[T, None]]:
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

    async def rewind_gen() -> collections.abc.AsyncGenerator[T, None]:
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
async def set_status_to_running_task(
    run_id: str | None, logger
) -> collections.abc.AsyncGenerator[asyncio.Task | None, None]:
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
            logger.warn(
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


class JsonScalar(pa.ExtensionScalar):
    """Represents a JSON binary string."""

    def as_py(self) -> dict | None:
        """Try to convert value to Python representation.

        We attempt to decode the value returned by `as_py` as JSON 3 times:
        1. As returned by `as_py`, without changes.
        2. By escaping and replacing any encoding errors.
        3. By treating the value as a string and surrouding it with quotes.

        If all else fails, we will log the offending value and re-raise the decoding error.
        """
        if self.value:
            value = self.value.as_py()

            if not value:
                return None

            json_bytes = value.encode("utf-8")

            try:
                return orjson.loads(json_bytes)
            except orjson.JSONDecodeError:
                pass

            json_bytes = value.encode("unicode-escape").decode("utf-8", "replace").encode("unicode-escape")
            try:
                return orjson.loads(json_bytes)
            except orjson.JSONDecodeError:
                pass

            if isinstance(value, str) and len(value) > 0 and not value.startswith("{") and not value.endswith("}"):
                # Handles non-valid JSON strings like `'"$set": "Something"'` by quoting them.
                value = f'"{value}"'

            json_bytes = value.encode("unicode-escape").decode("utf-8", "replace").encode("unicode-escape")
            try:
                return orjson.loads(json_bytes)
            except orjson.JSONDecodeError:
                logger.exception("Failed to decode with orjson: %s", value)
                raise

        else:
            return None


class JsonType(pa.ExtensionType):
    """Type for JSON binary strings."""

    def __init__(self):
        super().__init__(pa.string(), "json")

    def __arrow_ext_serialize__(self):
        return b""

    @classmethod
    def __arrow_ext_deserialize__(self, storage_type, serialized):
        return JsonType()

    def __arrow_ext_scalar_class__(self):
        return JsonScalar


def cast_record_batch_json_columns(
    record_batch: pa.RecordBatch,
    json_columns: collections.abc.Sequence = ("properties", "person_properties", "set", "set_once"),
) -> pa.RecordBatch:
    """Cast json_columns in record_batch to JsonType.

    We return a new RecordBatch with any json_columns replaced by fields casted to JsonType.
    Casting is not copying the underlying array buffers, so memory usage does not increase when creating
    the new array or the new record batch.
    """
    column_names = set(record_batch.column_names)
    intersection = column_names & set(json_columns)

    casted_arrays = []
    for array in record_batch.select(intersection):
        if pa.types.is_string(array.type):
            casted_array = array.cast(JsonType())
            casted_arrays.append(casted_array)

    remaining_column_names = list(column_names - intersection)
    return pa.RecordBatch.from_arrays(
        record_batch.select(remaining_column_names).columns + casted_arrays,
        names=remaining_column_names + list(intersection),
    )


_Result = typing.TypeVar("_Result")
FutureLike = (
    asyncio.Future[_Result] | collections.abc.Coroutine[None, typing.Any, _Result] | collections.abc.Awaitable[_Result]
)


def make_retryable_with_exponential_backoff(
    func: typing.Callable[..., collections.abc.Awaitable[_Result]],
    timeout: float | int | None = None,
    max_attempts: int = 5,
    initial_retry_delay: float | int = 2,
    max_retry_delay: float | int = 32,
    exponential_backoff_coefficient: int = 2,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    is_exception_retryable: typing.Callable[[Exception], bool] = lambda _: True,
) -> typing.Callable[..., collections.abc.Awaitable[_Result]]:
    """Retry the provided async `func` until `max_attempts` is reached."""
    functools.wraps(func)

    async def inner(*args, **kwargs):
        attempt = 0

        while True:
            try:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)

            except retryable_exceptions as err:
                attempt += 1

                if is_exception_retryable(err) is False or attempt >= max_attempts:
                    raise

                await asyncio.sleep(
                    min(max_retry_delay, initial_retry_delay * (attempt**exponential_backoff_coefficient))
                )

            else:
                return result

    return inner
