import abc
import asyncio
import collections.abc

import pyarrow as pa
import temporalio.common

from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.metrics import get_bytes_exported_metric, get_rows_exported_metric
from products.batch_exports.backend.temporal.pipeline.transformer import TransformerProtocol
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, raise_on_task_failure
from products.batch_exports.backend.temporal.utils import (
    cast_record_batch_json_columns,
    cast_record_batch_schema_json_columns,
)

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

    @property
    def rows_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the rows exported metric counter."""
        return get_rows_exported_metric()

    @property
    def bytes_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the bytes exported metric counter."""
        return get_bytes_exported_metric()

    async def start(
        self,
        queue: RecordBatchQueue,
        producer_task: asyncio.Task,
        schema: pa.Schema,
        transformer: TransformerProtocol,
        max_file_size_bytes: int = 0,
        json_columns: collections.abc.Iterable[str] = ("properties", "person_properties", "set", "set_once"),
    ) -> BatchExportResult:
        """Start consuming record batches from queue.

        Record batches will be processed by the `transformer`, which transforms the record batch into chunks of bytes,
        depending on the `file_format` and `compression`.

        Each of these chunks will be consumed by the `consume_chunk` method, which is implemented by subclasses.

        If `max_file_size_bytes` is set, we split the file into multiples if the file size exceeds this value.

        # TODO - we may need to support `multiple_files` here in future.
        Callers can control whether a new file is created for each flush or whether we
        continue flushing to the same file by setting `multiple_files`. File data is
        reset regardless, so this is not meant to impact total file size, but rather
        to control whether we are exporting a single large file in multiple parts, or
        multiple files that must each individually be valid.

        Returns:
            BatchExportResult:
                - The total number of records in all consumed record batches. If an error occurs, this will be None.
                - The total number of bytes exported (this is the size of the actual data exported, which takes into
                    account the file type and compression). If an error occurs, this will be None.
                - The error that occurred, if any. If no error occurred, this will be None. If an error occurs, this
                    will be a string representation of the error.
        """

        schema = cast_record_batch_schema_json_columns(schema, json_columns=json_columns)
        num_records_in_batch = 0
        num_bytes_in_batch = 0
        total_record_batches_count = 0
        total_records_count = 0
        total_record_batch_bytes_count = 0
        total_file_bytes_count = 0

        async def track_iteration_of_record_batches():
            """Wrap generator of record batches to track execution."""
            nonlocal num_records_in_batch
            nonlocal num_bytes_in_batch
            nonlocal total_record_batches_count
            nonlocal total_records_count
            nonlocal total_record_batch_bytes_count

            async for record_batch in self.generate_record_batches_from_queue(queue, producer_task):
                record_batch = cast_record_batch_json_columns(record_batch, json_columns=json_columns)

                total_record_batches_count += 1
                num_records_in_batch = record_batch.num_rows
                total_records_count += num_records_in_batch
                num_bytes_in_batch = record_batch.nbytes
                total_record_batch_bytes_count += num_bytes_in_batch

                self.rows_exported_counter.add(num_records_in_batch)

                self.logger.info(
                    f"Consuming {num_records_in_batch:,} records, {num_bytes_in_batch / 1024**2:.2f} MiB from record "
                    f"batch {total_record_batches_count}. Total records so far: {total_records_count:,}, "
                    f"total MiB so far: {total_record_batch_bytes_count / 1024**2:.2f}, "
                    f"total file MiB so far: {total_file_bytes_count / 1024**2:.2f}"
                )

                yield record_batch

        self.logger.info("Starting consumer from internal S3 stage")

        try:
            async for chunk, is_eof in transformer.iter(
                track_iteration_of_record_batches(),
                max_file_size_bytes,
            ):
                chunk_size = len(chunk)
                total_file_bytes_count += chunk_size

                await self.consume_chunk(data=chunk)
                self.bytes_exported_counter.add(chunk_size)

                if is_eof:
                    await self.finalize_file()

            await self.finalize()

        except Exception:
            self.logger.exception("Unexpected error occurred while consuming record batches")
            raise

        self.logger.info(
            f"Finished consuming {total_records_count:,} records, {total_record_batch_bytes_count / 1024**2:.2f} MiB "
            f"from {total_record_batches_count:,} record batches. "
            f"Total file MiB: {total_file_bytes_count / 1024**2:.2f}"
        )
        return BatchExportResult(total_records_count, total_file_bytes_count)

    async def generate_record_batches_from_queue(
        self,
        queue: RecordBatchQueue,
        producer_task: asyncio.Task,
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

            yield record_batch

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
    transformer: TransformerProtocol,
    schema: pa.Schema,
    max_file_size_bytes: int = 0,
    json_columns: collections.abc.Iterable[str] = ("properties", "person_properties", "set", "set_once"),
) -> BatchExportResult:
    """Run a consumer that takes record batches from a queue and writes them to a destination.

    This uses a newer version of the consumer that works with the internal S3 stage activities.

    Arguments:
        queue: The queue to consume record batches from.
        consumer: The consumer to run.
        producer_task: The task that produces record batches.
        schema: The schema of the record batches.
        file_format: The format of the file to write to.
        compression: The compression to use for the file.
        include_inserted_at: Whether to include the inserted_at column in the file.
        max_file_size_bytes: The maximum size of the file to write to (if 0, no file splitting is done)
        json_columns: The columns which contain JSON data.

    Returns:
        BatchExportResult (A tuple containing):
            - The total number of records in all consumed record batches.
            - The total number of bytes exported (this is the size of the actual data exported, which takes into
                account the file type and compression).
    """
    result = await consumer.start(
        queue=queue,
        producer_task=producer_task,
        schema=schema,
        transformer=transformer,
        max_file_size_bytes=max_file_size_bytes,
        json_columns=json_columns,
    )

    await raise_on_task_failure(producer_task)
    return result
