import abc
import time
import typing
import asyncio
import operator
import collections.abc

import temporalio.common

from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.metrics import get_bytes_exported_metric, get_rows_exported_metric
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.pipeline.transformer import ChunkTransformerProtocol
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, raise_on_task_failure

if typing.TYPE_CHECKING:
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
        self.record_batches_per_second = 0

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
        self.record_batches_per_second = 0

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

            self.logger.debug(f"Consuming batch number {self.total_record_batches_count}")

            if json_columns:
                record_batch = cast_record_batch_json_columns(record_batch, json_columns=json_columns)

            yield record_batch

            num_records_in_batch = record_batch.num_rows
            self.total_records_count += num_records_in_batch
            num_bytes_in_batch = record_batch.nbytes
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


_GET_TOTAL_RECORD_BATCH_BYTES_COUNT = operator.attrgetter("total_record_batch_bytes_count")


class ConsumerPool:
    def __init__(
        self,
        target_duration: int | float,
        queue: RecordBatchQueue,
        producer: Producer,
        transformer: ChunkTransformerProtocol,
        max_consumers: int,
        consumer_cls: type[Consumer],
        json_columns: collections.abc.Iterable[str] = ("properties", "person_properties", "set", "set_once"),
        **consumer_kwargs,
    ):
        self.queue = queue
        self.producer = producer
        self.transformer = transformer
        self.max_consumers = max_consumers
        self.consumer_cls = consumer_cls
        self.consumer_kwargs = consumer_kwargs
        self.json_columns = json_columns
        self.target_duration = target_duration
        self.logger = LOGGER.bind(max_consumers=max_consumers, target_duration=target_duration)

        self.__task_group = None
        self._consumers = set()
        self.__scaler = None
        self.__start_time = None
        self._last_poll_time = None
        self._total_bytes_consumed = 0
        self._poll_delay = 10

    @property
    def _task_group(self) -> asyncio.TaskGroup:
        if self.__task_group is None:
            raise ValueError("consumer pool not started")
        return self.__task_group

    @property
    def _scaler(self) -> asyncio.Task[None]:
        if self.__scaler is None:
            raise ValueError("consumer pool not started")
        return self.__scaler

    @property
    def _start_time(self) -> float:
        if self.__start_time is None:
            raise ValueError("consumer pool not started")
        return self.__start_time

    @property
    def number_of_consumers(self) -> int:
        return len(self._consumers)

    def is_at_max_consumers(self):
        return self.number_of_consumers >= self.max_consumers

    async def __aenter__(self):
        self.__task_group = await asyncio.TaskGroup().__aenter__()
        self.__start_time = time.monotonic()
        self.__scaler = self._start_scaler()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _ = self._scaler.cancel()
        await self._task_group.__aexit__(exc_type, exc, tb)

    def _start_consumer(self):
        consumer = self.consumer_cls(**self.consumer_kwargs)
        self._consumers.add(consumer)
        self.task_group.create_task(
            self.consumer_cls(**self.consumer_kwargs).start(
                queue=self.queue,
                producer_task=self.producer.task,
                transformer=self.transformer,
                json_columns=self.json_columns,
            )
        )

        self.logger.info("Consumer started")

    def _start_scaler(self) -> asyncio.Task[None]:
        return asyncio.create_task(self._scale_loop())

    async def _scale_loop(self) -> None:
        await asyncio.sleep(self._poll_delay)

        while True:
            if len(self._consumers) >= self.max_consumers:
                # Exit as we have scaled as much as we are allowed to
                break

            now = time.monotonic()
            if self._last_poll_time is not None:
                period_seconds = now - self._last_poll_time
            else:
                period_seconds = now - self._start_time

            current_total_bytes_consumed = sum(map(_GET_TOTAL_RECORD_BATCH_BYTES_COUNT, self.consumers))
            bytes_consumed_in_period = current_total_bytes_consumed - self._total_bytes_consumed

            if period_seconds <= 0 or bytes_consumed_in_period <= 0:
                self._last_poll_time = now
                await asyncio.sleep(self._poll_delay)
                continue

            bytes_consumption_rate_in_period = bytes_consumed_in_period / period_seconds
            estimated_seconds_left = (
                self.producer.total_size - current_total_bytes_consumed
            ) / bytes_consumption_rate_in_period

            total_time_elapsed = now - self._start_time

            # Add consumers if we are over the target duration or if we estimate we will be over
            if total_time_elapsed > self.target_duration:
                # We have missed our target, scale as much as we can and exit
                self._start_max_consumers()
                break

            elif estimated_seconds_left > (self.target_duration - total_time_elapsed):
                consumers_to_add = _compute_consumers_to_add(
                    bytes_left=self.producer.total_size - current_total_bytes_consumed,
                    time_left=self.target_duration - total_time_elapsed,
                    bytes_consumption_rate=bytes_consumption_rate_in_period,
                    current_consumers=self.number_of_consumers,
                    max_consumers=self.max_consumers,
                )

                for _ in range(consumers_to_add):
                    self._start_consumer()

            self._total_bytes_consumed = current_total_bytes_consumed
            await asyncio.sleep(self._poll_delay)

    def _start_max_consumers(self):
        while not self.is_at_max_consumers():
            self._start_consumer()


def _compute_consumers_to_add(
    bytes_left: int,
    time_left: int | float,
    bytes_consumption_rate: int | float,
    current_consumers: int,
    max_consumers: int,
) -> int:
    target_bytes_consumption_rate = bytes_left / time_left
    bytes_consumption_rate_per_consumer = bytes_consumption_rate / current_consumers
    number_of_consumers_needed = target_bytes_consumption_rate / bytes_consumption_rate_per_consumer
    target_consumers_to_add = int(number_of_consumers_needed - current_consumers)
    bounded_consumers_to_add = min(max(target_consumers_to_add, 0), max_consumers - current_consumers)

    return bounded_consumers_to_add
