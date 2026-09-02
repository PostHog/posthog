"""The bounded queue that carries record batches from a producer to a consumer.

Batch exports move data by having a producer read record batches and a consumer write them to
the destination. This is the handoff between them: a queue bounded by bytes rather than item
count, since record batch sizes vary enormously, plus the helpers for waiting on the producer
and surfacing its failures.
"""

import time
import typing
import asyncio
import collections.abc

import pyarrow as pa
from temporalio.common import MetricHistogram

from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.temporal.metrics import get_metric_meter

LOGGER = get_write_only_logger(__name__)


class QueuedRecordBatch(typing.NamedTuple):
    """A record batch in queue, tracking the time it entered."""

    record_batch: pa.RecordBatch
    enqueued_at: int


class RecordBatchQueue(asyncio.Queue):
    """A queue of pyarrow RecordBatch instances limited by bytes."""

    def __init__(self, max_size_bytes: int = 0) -> None:
        super().__init__(maxsize=max_size_bytes)
        self._bytes_size = 0
        self._schema_set = asyncio.Event()
        self.record_batch_schema: pa.Schema | None = None
        self._histogram: MetricHistogram | None = None
        # This is set by `asyncio.Queue.__init__` calling `_init`
        self._queue: collections.deque[QueuedRecordBatch]

    @property
    def histogram(self) -> MetricHistogram:
        if self._histogram is None:
            meter = get_metric_meter()
            self._histogram = meter.create_histogram(
                "batch_exports_queue_wait_time", description="Time spent by record batches waiting in queue"
            )
        return self._histogram

    def _get(self) -> pa.RecordBatch:
        """Override parent `_get` to keep track of bytes."""
        record_batch, enqueued_at = self._queue.popleft()
        self._bytes_size -= record_batch.get_total_buffer_size()

        queued_time = time.perf_counter_ns() - enqueued_at
        self.histogram.record(queued_time)

        return record_batch

    def _put(self, item: pa.RecordBatch) -> None:
        """Override parent `_put` to keep track of bytes."""
        self._bytes_size += item.get_total_buffer_size()

        if not self._schema_set.is_set():
            self.set_schema(item)

        self._queue.append(QueuedRecordBatch(item, time.perf_counter_ns()))

    def set_schema(self, record_batch: pa.RecordBatch) -> None:
        """Used to keep track of schema of events in queue."""
        self.record_batch_schema = record_batch.schema
        self._schema_set.set()

    async def get_schema(self) -> pa.Schema:
        """Return the schema of events in queue.

        Currently, this is not enforced. It's purely for reporting to users of
        the queue what do the record batches look like. It's up to the producer
        to ensure all record batches have the same schema.
        """
        await self._schema_set.wait()
        assert self.record_batch_schema is not None
        return self.record_batch_schema

    def qsize(self) -> int:
        """Size in bytes of record batches in the queue.

        This is used to determine when the queue is full, so it returns the
        number of bytes.
        """
        return self._bytes_size

    def __repr__(self):
        return f"<{type(self).__name__} at {id(self):#x} {self._format()}>"

    def __str__(self):
        return f"<{type(self).__name__} {self._format()}>"

    def _format(self) -> str:
        result = f"record_batches={len(self._queue)}"
        result += f" bytes={str(self._bytes_size)}"
        if self.record_batch_schema is not None:
            result += f" schema='{self.record_batch_schema}'"
        return result


class TaskNotDoneError(Exception):
    """Raised when a task that should be done, isn't."""

    def __init__(self, task: str):
        super().__init__(f"Expected task '{task}' to be done by now")


class RecordBatchTaskError(Exception):
    """Raised when an error occurs during consumption of record batches."""

    def __init__(self, error_details: str):
        super().__init__(f"Record batch consumer encountered an error: {error_details}")


async def raise_on_task_failure(task: asyncio.Task) -> None:
    """Raise `RecordBatchTaskError` if a producer task failed.

    We will also raise a `TaskNotDone` if the producer is not done, as this
    should only be called after producer is done to check its exception.
    """
    if not task.done():
        raise TaskNotDoneError(task.get_name())

    if task.exception() is None:
        return

    exc = task.exception()
    LOGGER.exception("%s task failed", task.get_name(), exc_info=exc)
    raise RecordBatchTaskError(repr(exc)) from exc


async def wait_for_schema_or_producer(queue: RecordBatchQueue, producer_task: asyncio.Task) -> pa.Schema | None:
    """Wait for a queue schema to be set or a producer to finish.

    If the queue's schema is set first, we will return that, otherwise we return
    `None`.

    A queue's schema will be set sequentially on the first record batch produced.
    So, after waiting for both tasks, either we finished setting the schema and
    have partially or fully produced record batches, or we finished without putting
    anything in the queue, and the queue's schema has not been set.
    """
    record_batch_schema = None

    get_schema_task = asyncio.create_task(queue.get_schema())

    await asyncio.wait(
        [get_schema_task, producer_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if get_schema_task.done():
        # The schema is available, and the queue is not empty, so we can continue
        # with the rest of the the batch export.
        record_batch_schema = get_schema_task.result()
    else:
        # We finished producing without putting anything in the queue and there is
        # nothing to batch export. We could have also failed, so we need to re-raise
        # that exception to allow a retry if that's the case. If we don't fail, it
        # is safe to finish the batch export early.
        await raise_on_task_failure(producer_task)

    return record_batch_schema
