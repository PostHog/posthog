import asyncio
import collections.abc
import contextlib
import json
import typing
import uuid

import orjson
import pyarrow as pa

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import aupdate_batch_export_run

T = typing.TypeVar("T")


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
        if self.value:
            try:
                return orjson.loads(self.value.as_py().encode("utf-8"))
            except:
                # Fallback if it's something orjson can't handle
                return json.loads(self.value.as_py())
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
