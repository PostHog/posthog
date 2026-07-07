import abc
import enum
import time
import typing
import asyncio
import collections.abc

import pyarrow as pa
import temporalio.common
from opentelemetry import trace

from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.metrics import (
    Attributes,
    CumulativeTimer,
    get_bytes_exported_metric,
    get_rows_exported_metric,
)
from products.batch_exports.backend.temporal.pipeline.transformer import ChunkTransformerProtocol
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, raise_on_task_failure
from products.batch_exports.backend.temporal.utils import cast_record_batch_json_columns

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")
TRACER = trace.get_tracer(__name__)

# Determines how frequently we log export progress.
PROGRESS_LOG_STEP_PCT = 10


class _WaitResult(enum.Enum):
    """Enumeration of possible results when concurrently waiting for two tasks."""

    FIRST_DONE = (True, False)
    SECOND_DONE = (False, True)
    BOTH_DONE = (True, True)


class Consumer:
    """Consumer for batch exports.

    This is an alternative implementation of the `spmc.Consumer` class that consumes data from a producer which is in
    turn reading data from the internal S3 staging area.
    """

    def __init__(self, model: str = "events"):
        self.logger = LOGGER.bind()
        self.external_logger = EXTERNAL_LOGGER.bind()
        self.model = model

        # Total rows expected for this run (from the staged ClickHouse count). When set, the
        # consumer logs export progress as a percentage of records delivered to the destination.
        self.records_total: int | None = None

        # Progress tracking
        self.total_record_batches_count = 0
        self.total_records_count = 0
        self.total_record_batch_bytes_count = 0
        self.total_file_bytes_count = 0
        self.records_failed_count = 0
        self._start_monotonic: float | None = None
        self._next_progress_pct = PROGRESS_LOG_STEP_PCT

        # Stage-attribution timers, reported as span attributes:
        # Queue-get wait is time spent starved waiting for the producer
        self._queue_get_wait_timer = CumulativeTimer()
        # consume time is time spent handing chunks to the destination consumer
        # (`consume_chunk`/`finalize_file`/`finalize`).
        self._consume_timer = CumulativeTimer()

    @property
    def rows_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the rows exported metric counter."""
        return get_rows_exported_metric(model=self.model)

    @property
    def bytes_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the bytes exported metric counter."""
        return get_bytes_exported_metric(model=self.model)

    def reset_tracking(self) -> None:
        self.total_record_batches_count = 0
        self.total_records_count = 0
        self.total_record_batch_bytes_count = 0
        self.total_file_bytes_count = 0
        self.records_failed_count = 0
        self._start_monotonic = None
        self._next_progress_pct = PROGRESS_LOG_STEP_PCT
        self._queue_get_wait_timer = CumulativeTimer()
        self._consume_timer = CumulativeTimer()

    async def start(
        self,
        queue: RecordBatchQueue,
        producer_task: asyncio.Task,
        transformer: ChunkTransformerProtocol,
        json_columns: collections.abc.Iterable[str] = ("properties", "person_properties", "set", "set_once"),
    ) -> BatchExportResult:
        """Start consuming record batches from queue.

        Record batches will be processed by the `transformer`, which transforms the
        record batch into chunks of bytes, depending on the `file_format` and
        `compression`.
        Each of these chunks will be consumed by the `consume_chunk` method, which is
        implemented by subclasses.
        Returns:
            BatchExportResult:
                - The total number of records in all consumed record batches. If an
                  error occurs, this will be None.
                - The total number of bytes exported (this is the size of the actual data
                  exported, which takes into account the file type and compression). If
                  an error occurs, this will be None.
                - The error that occurred, if any. If no error occurred, this will be
                  None. If an error occurs, this will be a string representation of the
                  error.
        """

        self.reset_tracking()
        start_monotonic = time.monotonic()
        self._start_monotonic = start_monotonic

        self.logger.info("Starting consumer from internal S3 stage")

        with TRACER.start_as_current_span("batch_export.consumer") as span:
            try:
                async for chunk, is_eof in transformer.iter(
                    self.generate_record_batches_from_queue(queue, producer_task, json_columns),
                ):
                    chunk_size = len(chunk)
                    self.total_file_bytes_count += chunk_size

                    with self._consume_timer.time():
                        await self.consume_chunk(data=chunk)
                    self.bytes_exported_counter.add(chunk_size)

                    if is_eof:
                        with self._consume_timer.time():
                            await self.finalize_file()

                with self._consume_timer.time():
                    await self.finalize()

            except Exception:
                self.logger.exception("Unexpected error occurred while consuming record batches")
                raise
            finally:
                self._set_stage_attribution_span_attributes(span, elapsed=time.monotonic() - start_monotonic)

        self.logger.info(
            f"Finished consuming {self.total_records_count:,} records, {self.total_record_batch_bytes_count / 1024**2:.2f} MiB "
            f"from {self.total_record_batches_count:,} record batches. "
            f"Total file MiB: {self.total_file_bytes_count / 1024**2:.2f}"
        )
        return BatchExportResult(self.total_records_count, self.total_file_bytes_count)

    def _set_stage_attribution_span_attributes(self, span: trace.Span, elapsed: float) -> None:
        """Report where consumer time went as attributes on the consumer span.

        It's unrealistic to create spans for each individual call to queue.get(), consume_chunk(),
        etc. as there could be thousands of these for larger batch exports. However, tracking and
        reporting the cumulative time spent in each of these tasks is useful for monitoring where
        potential bottlenecks lie.
        """
        consume_seconds = self._consume_timer.total_seconds
        queue_get_wait_seconds = self._queue_get_wait_timer.total_seconds
        # What's left after subtracting consume time and queue starvation is
        # transformation time, plus a small amount of loop overhead.
        transform_seconds = max(0.0, elapsed - consume_seconds - queue_get_wait_seconds)
        span.set_attributes(
            {
                "batch_export.consumer.records_consumed": self.total_records_count,
                "batch_export.consumer.bytes_exported": self.total_file_bytes_count,
                "batch_export.consumer.total_queue_get_wait_seconds": queue_get_wait_seconds,
                "batch_export.consumer.total_consume_seconds": consume_seconds,
                "batch_export.consumer.total_transform_seconds": transform_seconds,
                **self.get_destination_span_attributes(),
            }
        )

    def get_destination_span_attributes(self) -> Attributes:
        """Destination-specific attributes to report on the consumer span.

        Subclasses can override this to break down where their consume time goes
        (e.g. time blocked on destination upload capacity).
        """
        return {}

    def collect_result(self) -> BatchExportResult:
        """Collect the result of the consumer.

        A little bit of a hack that can be used by callers to collect the result of the consumer after we're sure all
        remaining asyncio tasks have completed.

        Currently only used by the Workflows batch export destination.

        TODO: Refactor the consumer to work as a context manager to avoid this.
        """
        return BatchExportResult(
            records_completed=self.total_records_count - self.records_failed_count,
            bytes_exported=self.total_file_bytes_count,
            records_failed=self.records_failed_count,
        )

    async def generate_record_batches_from_queue(
        self,
        queue: RecordBatchQueue,
        producer_task: asyncio.Task,
        json_columns: collections.abc.Iterable[str] = ("properties", "person_properties", "set", "set_once"),
    ):
        """Yield record batches from provided `queue` until `producer_task` is done.

        This method is non-blocking by concurrently waiting for both `queue.get` and
        `producer_task` in a loop using `asyncio.wait`.

        Everytime `queue.get` returns a value it is yielded. Whenever `producer_task` is
        done, we check if `queue` is empty. If it is, then the method doesn't expect
        anything else to ever come in the queue, and thus can exit without data loss
        (after canceling a pending `queue.get` to avoid resource leaking).

        If the `queue` is not empty, then the method can't exit just yet and instead
        continues waiting on `queue.get`.
        """

        while True:
            get_task = asyncio.create_task(queue.get())
            with self._queue_get_wait_timer.time():
                _ = await asyncio.wait((get_task, producer_task), return_when=asyncio.FIRST_COMPLETED)

            wait_result = _WaitResult((get_task.done(), producer_task.done()))
            match wait_result:
                case _WaitResult.FIRST_DONE | _WaitResult.BOTH_DONE:
                    record_batch = get_task.result()

                case _WaitResult.SECOND_DONE:
                    if queue.empty():
                        self.logger.debug(
                            "Empty queue with no more events being produced, closing writer loop and flushing"
                        )
                        get_task.cancel()
                        break
                    else:
                        with self._queue_get_wait_timer.time():
                            record_batch = await get_task

                case _:
                    typing.assert_never(wait_result)

            self.logger.debug(f"Consuming batch number {self.total_record_batches_count}")

            if json_columns:
                record_batch = cast_record_batch_json_columns(record_batch, json_columns=json_columns)

            yield record_batch

            self.track_record_batch(record_batch)

    def track_record_batch(self, record_batch: pa.RecordBatch) -> None:
        """Track consumer progress based on the last consumed record batch."""

        num_records_in_batch = record_batch.num_rows
        num_bytes_in_batch = record_batch.nbytes

        self.total_records_count += num_records_in_batch
        self.total_record_batch_bytes_count += num_bytes_in_batch
        self.rows_exported_counter.add(num_records_in_batch)

        self.logger.debug(
            f"Consumed batch number {self.total_record_batches_count} with "
            f"{num_records_in_batch:,} records, {num_bytes_in_batch / 1024**2:.2f} "
            f"MiB. Total records consumed so far: {self.total_records_count:,}, "
            f"total MiB consumed so far: {self.total_record_batch_bytes_count / 1024**2:.2f}, "
            f"total file MiB consumed so far: {self.total_file_bytes_count / 1024**2:.2f}"
        )

        self.total_record_batches_count += 1

        self._maybe_log_progress()

    def _maybe_log_progress(self) -> None:
        """Log export progress whenever a 10% step is crossed.

        Progress is measured in records delivered to the destination against the total
        staged for this run (from ClickHouse), so it reflects how far through the export
        we actually are. We report the actual percentage reached (e.g. ~11%) rather than
        the floored step, then advance the threshold to the next 10% boundary above the
        current position. Silent when the total is unknown (e.g. the stage couldn't
        report a count).
        """
        # `_start_monotonic` is set by `start()` before the consume loop, and this is only
        # called from within it, so it should always be set during a run.
        if not self.records_total or self._start_monotonic is None:
            return

        records = min(self.total_records_count, self.records_total)
        pct = records / self.records_total * 100
        if pct < self._next_progress_pct:
            return

        elapsed = time.monotonic() - self._start_monotonic
        rows_per_second = int(records / elapsed) if elapsed > 0 else 0
        self.logger.info(
            f"Exported ~{int(pct)}% to destination "
            f"({records:,} of ~{self.records_total:,} records), ~{rows_per_second:,} rows/s"
        )
        self._next_progress_pct = (int(pct // PROGRESS_LOG_STEP_PCT) + 1) * PROGRESS_LOG_STEP_PCT

    @abc.abstractmethod
    async def consume_chunk(self, data: bytes):
        """Consume a chunk of data."""
        pass

    @abc.abstractmethod
    async def finalize_file(self):
        """Finalize the current file.

        Only called if working with multiple files, such as when we have a max file size.
        """
        pass

    @abc.abstractmethod
    async def finalize(self):
        """Finalize the consumer."""
        pass


async def run_consumer_from_stage(
    queue: RecordBatchQueue,
    consumer: Consumer,
    producer_task: asyncio.Task[None],
    transformer: ChunkTransformerProtocol,
    json_columns: collections.abc.Iterable[str] = ("properties", "person_properties", "set", "set_once"),
    records_total: int | None = None,
) -> BatchExportResult:
    """Run a record batch consumer to batch export to a destination.

    The consumer reads record from a queue populated by a producer that fetches them
    from an the internal S3 bucket.

    Arguments:
        queue: The queue to consume record batches from.
        consumer: The consumer to run.
        producer_task: The task that produces record batches.
        transformer: The transformer used to convert record batches into their desired
            export format.
        records_total: Total rows staged for this run (from ClickHouse). When provided, the
            consumer logs export progress as a percentage of records delivered.

    Returns:
        BatchExportResult (A tuple containing):
            - The total number of records in all consumed record batches.
            - The total number of bytes exported (this is the size of the actual data
                exported, which takes into account the file type and compression).
    """
    consumer.records_total = records_total
    result = await consumer.start(
        queue=queue,
        producer_task=producer_task,
        transformer=transformer,
        json_columns=json_columns,
    )

    await raise_on_task_failure(producer_task)
    return result
