import abc
import asyncio
import collections.abc

import temporalio.common

from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.metrics import get_bytes_exported_metric, get_rows_exported_metric
from products.batch_exports.backend.temporal.pipeline.transformer import ChunkTransformerProtocol
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, raise_on_task_failure
from products.batch_exports.backend.temporal.utils import cast_record_batch_json_columns

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")


class Consumer:
    """Consumer for batch exports.

    This is an alternative implementation of the `spmc.Consumer` class that consumes data from a producer which is in
    turn reading data from the internal S3 staging area.
    """

    def __init__(self):
        self.logger = LOGGER.bind()
        self.external_logger = EXTERNAL_LOGGER.bind()

        # Progress tracking
        self.total_record_batches_count = 0
        self.total_records_count = 0
        self.total_record_batch_bytes_count = 0
        self.total_file_bytes_count = 0

    @property
    def rows_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the rows exported metric counter."""
        return get_rows_exported_metric()

    @property
    def bytes_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the bytes exported metric counter."""
        return get_bytes_exported_metric()

    def reset_tracking(self) -> None:
        self.total_record_batches_count = 0
        self.total_records_count = 0
        self.total_record_batch_bytes_count = 0
        self.total_file_bytes_count = 0

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

        self.logger.info("Starting consumer from internal S3 stage")

        try:
            async for chunk, is_eof in transformer.iter(
                self.generate_record_batches_from_queue(queue, producer_task, json_columns),
            ):
                chunk_size = len(chunk)
                self.total_file_bytes_count += chunk_size

                await self.consume_chunk(data=chunk)
                self.bytes_exported_counter.add(chunk_size)

                if is_eof:
                    await self.finalize_file()

            await self.finalize()

        except Exception:
            self.logger.exception("Unexpected error occurred while consuming record batches")
            raise

        self.logger.info(
            f"Finished consuming {self.total_records_count:,} records, {self.total_record_batch_bytes_count / 1024**2:.2f} MiB "
            f"from {self.total_record_batches_count:,} record batches. "
            f"Total file MiB: {self.total_file_bytes_count / 1024**2:.2f}"
        )
        return BatchExportResult(self.total_records_count, self.total_file_bytes_count)

    async def generate_record_batches_from_queue(
        self,
        queue: RecordBatchQueue,
        producer_task: asyncio.Task,
        json_columns: collections.abc.Iterable[str] = ("properties", "person_properties", "set", "set_once"),
    ):
        """Yield record batches from provided `queue` until `producer_task` is done."""

        while True:
            try:
                record_batch = queue.get_nowait()
            except asyncio.QueueEmpty:
                if producer_task.done():
                    self.logger.debug(
                        "Empty queue with no more events being produced, closing writer loop and flushing"
                    )
                    break
                else:
                    await asyncio.sleep(0)
                    continue

            self.logger.info(f"Consuming batch number {self.total_record_batches_count}")

            record_batch = cast_record_batch_json_columns(record_batch, json_columns=json_columns)

            yield record_batch

            num_records_in_batch = record_batch.num_rows
            self.total_records_count += num_records_in_batch
            num_bytes_in_batch = record_batch.nbytes
            self.total_record_batch_bytes_count += num_bytes_in_batch
            self.rows_exported_counter.add(num_records_in_batch)

            self.logger.info(
                f"Consumed batch number {self.total_record_batches_count} with "
                f"{num_records_in_batch:,} records, {num_bytes_in_batch / 1024**2:.2f} "
                f"MiB. Total records consumed so far: {self.total_records_count:,}, "
                f"total MiB consumed so far: {self.total_record_batch_bytes_count / 1024**2:.2f}, "
                f"total file MiB consumed so far: {self.total_file_bytes_count / 1024**2:.2f}"
            )

            self.total_record_batches_count += 1

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

    Returns:
        BatchExportResult (A tuple containing):
            - The total number of records in all consumed record batches.
            - The total number of bytes exported (this is the size of the actual data
                exported, which takes into account the file type and compression).
    """
    result = await consumer.start(
        queue=queue,
        producer_task=producer_task,
        transformer=transformer,
        json_columns=json_columns,
    )

    await raise_on_task_failure(producer_task)
    return result
