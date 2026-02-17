import abc
import enum
import time
import typing
import asyncio
import operator
import dataclasses
import collections.abc

import pyarrow as pa
import temporalio.common

from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.temporal.metrics import get_bytes_exported_metric, get_rows_exported_metric
from products.batch_exports.backend.temporal.pipeline.transformer import ChunkTransformerProtocol
from products.batch_exports.backend.temporal.pipeline.types import BatchExportError, BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, raise_on_task_failure
from products.batch_exports.backend.temporal.utils import cast_record_batch_json_columns

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")
ConsumerCoroutine = collections.abc.Coroutine[None, None, BatchExportResult]
ConsumerTask = asyncio.Task[BatchExportResult]


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
        self._task: ConsumerTask | None = None

        # Progress tracking
        self.total_record_batches_count = 0
        self.total_records_count = 0
        self.total_record_batch_bytes_count = 0
        self.total_file_bytes_count = 0

    @property
    def rows_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the rows exported metric counter."""
        return get_rows_exported_metric(model=self.model)

    @property
    def bytes_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the bytes exported metric counter."""
        return get_bytes_exported_metric(model=self.model)

    @property
    def task(self) -> ConsumerTask:
        if self._task is None:
            raise ValueError("Consumer task is not initialized, have you called `Consumer.start()`?")
        return self._task

    def done(self) -> bool:
        try:
            return self.task.done()
        except ValueError:
            return False

    def start(
        self,
        queue: RecordBatchQueue,
        producer_task: asyncio.Task,
        transformer: ChunkTransformerProtocol,
        json_columns: collections.abc.Iterable[str] = ("properties", "person_properties", "set", "set_once"),
        task_group: asyncio.TaskGroup | None = None,
        name: str = "consumer",
    ) -> ConsumerTask:
        self.reset_tracking()

        fut = self.run(queue=queue, producer_task=producer_task, transformer=transformer, json_columns=json_columns)
        self._schedule_coro(fut, task_group, name)

        return self.task

    def _schedule_coro(
        self, coro: ConsumerCoroutine, task_group: asyncio.TaskGroup | None = None, name: str = "consumer"
    ):
        if task_group is not None:
            self._task = task_group.create_task(coro, name=name)
        else:
            self._task = asyncio.create_task(coro, name=name)

        self.logger = self.logger.bind(task_name=name)
        self.external_logger = self.external_logger.bind(task_name=name)

    def reset_tracking(self) -> None:
        self.total_record_batches_count = 0
        self.total_records_count = 0
        self.total_record_batch_bytes_count = 0
        self.total_file_bytes_count = 0

    async def run(
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
                        record_batch = await get_task

                case _:
                    typing.assert_never(wait_result)

            self.logger.info(f"Consuming batch number {self.total_record_batches_count}")

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

    @abc.abstractmethod
    async def consume_chunk(self, data: bytes) -> None:
        """Consume a chunk of data."""
        pass

    @abc.abstractmethod
    async def finalize_file(self) -> None:
        """Finalize the current file.

        Only called if working with multiple files, such as when we have a max file size.
        """
        pass

    @abc.abstractmethod
    async def finalize(self) -> None:
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
DEFAULT_MAX_CONSUMERS = 10
DEFAULT_MIN_CONSUMERS = 1
DEFAULT_POLL_DELAY_SECONDS = 3
DEFAULT_INITIAL_GRACE_PERIOD_SECONDS = 30
DEFAULT_TRACKING_WINDOW_SIZE = 5


@dataclasses.dataclass
class ConsumerGroupSettings:
    """Settings for a ``ConsumerGroup``.

    Attributes:
        target_duration_seconds: The duration the ``ConsumerGroup`` should aim for. It
            is recommended to set this to a fraction of the batch export interval, as we
            should always aim to finish with a good margin before the interval is up.
        total_size_bytes: Size of the batch export. This is hard to estimate during the
            consumer execution and also beforehand. Should be set based on historical
            data.
        initial_grace_period_seconds: An initial wait time before the ``ConsumerGroup``
            to starts polling to decide whether to scale up. This allows time for
            smaller batch exports that finish quickly to actually finish.
        poll_delay_seconds: How frequently the ``ConsumerGroup`` polls for metrics from
            all consumers. This represents a trade-off between time-to-scale and group
            overhead.
        tracking_window_size: ``ConsumerGroup`` only uses the last
            ``tracking_window_size`` observations to determine whether to adjust the
            number of consumers or not.
        max_consumers: Maximum number of consumers that can be added to a
            ``ConsumerGroup``.
        min_consumers: Minimum number of consumers that should be present in a
            ``ConsumerGroup``.
    """

    target_duration_seconds: int
    total_size_bytes: int
    initial_grace_period_seconds: int | float = DEFAULT_INITIAL_GRACE_PERIOD_SECONDS
    poll_delay_seconds: int | float = DEFAULT_POLL_DELAY_SECONDS
    tracking_window_size: int = DEFAULT_TRACKING_WINDOW_SIZE
    max_consumers: int = DEFAULT_MAX_CONSUMERS
    min_consumers: int = DEFAULT_MIN_CONSUMERS


_C = typing.TypeVar("_C", bound=Consumer)


class ConsumerGroup(typing.Protocol[_C]):
    """A protocol to manage a group of consumers.

    The provided methods can run and scale up the group after the necessary required
    members are implemented:
    * ``build_consumer``: Should provide a fresh instance of a ``Consumer`` (or a
      subclass) to run.
    * ``run_consumer``: Provided with the instance, it should return the consumer
      coroutine initialized by ``Consumer.run``.

    And ``GroupSettings`` are provided.

    Using this protocol allows whoever implements it to define how their consumers are
    initialized and started. As each destination has different requirements, a single
    class would not be able to represent all of them, so the flexibility of a protocol
    was needed.

    The group can only add consumers, not remove them. In the future this is a feature
    we may implement, but our main priority is that consumers can scale up to improve
    performance.
    """

    # Required settings
    settings: ConsumerGroupSettings

    # Tracking state
    records_completed: int = 0
    bytes_exported: int = 0
    bytes_exported_window: int = 0
    time_elapsed: int | float = 0
    time_elapsed_window: int | float = 0

    # Internal state management
    _consumers: set[_C] | None = None
    _errors: list[BatchExportError] | None = None
    _last_poll_time: int | float | None = None
    _start_time: int | float | None = None
    _window_counter: int = 0
    _window_start_time: int | float | None = None

    def build_consumer(self) -> _C: ...

    def run_consumer(self, consumer: _C) -> collections.abc.Coroutine[None, None, BatchExportResult]: ...

    @property
    def start_time(self) -> int | float:
        """Return the start time for the whole consumer group."""
        if self._start_time is None:
            raise ValueError("group not started")
        return self._start_time

    @property
    def last_poll_time(self) -> float:
        """Return the time when the last poll() call completed."""
        if self._last_poll_time is None:
            raise ValueError("group not started")
        return self._last_poll_time

    @property
    def window_start_time(self) -> float:
        """Return the start time for the current tracking window."""
        if self._window_start_time is None:
            raise ValueError("group not started")
        return self._window_start_time

    @property
    def number_of_consumers(self) -> int:
        """Return the current number of consumers."""
        return len(self.consumers)

    @property
    def bytes_exported_per_second(self) -> float:
        """Return the overall rate of exported bytes per second."""
        try:
            return self.bytes_exported / self.time_elapsed
        except ZeroDivisionError:
            raise ValueError("group not started")

    @property
    def bytes_exported_per_second_window(self) -> float:
        """Return the rate of exported bytes per second for the last window."""
        try:
            return self.bytes_exported_window / self.time_elapsed_window
        except ZeroDivisionError:
            raise ValueError("group not started")

    @property
    def consumers(self) -> set[_C]:
        """A set for all consumers in this group."""
        if self._consumers is None:
            self._consumers = set()
        return self._consumers

    @property
    def result(self) -> BatchExportResult:
        """Accumulated result of all consumers in this group."""
        return BatchExportResult(
            records_completed=self.records_completed, bytes_exported=self.bytes_exported, error=self.errors or None
        )

    @property
    def errors(self) -> list[BatchExportError]:
        """A list of all errors seen in consumers in this group."""
        if self._errors is None:
            self._errors = []
        return self._errors

    def done(self) -> bool:
        """If there is at least one consumer and all consumers are done, we are done."""
        return len(self.consumers) >= 1 and all(consumer.done() for consumer in self.consumers)

    async def run(self) -> BatchExportResult:
        """Run the consumer group until batch export is done.

        Each consumer is handed over to an ``asyncio.TaskGroup`` to manage clean-up.

        By frequently polling for consumption rates from all consumers, the group
        estimates the number of consumers needed to finish before
        ``self.settings.target_duration_seconds``:
        * If that number is above the current number of consumers, then the group will
          add enough consumers to meet the target.
        * Support for removing consumers if that number is below the current number of
          consumers instead is not currently available.

        Polling happens every ``self.settings.poll_delay_seconds`` but only starts after
        ``self.settings.initial_grace_period`` to allow batch exports that can finish
        quickly with a single consumer to do so.
        """
        async with asyncio.TaskGroup() as tg:
            # At least min_consumers will always be needed
            for _ in range(self.settings.min_consumers):
                self._add_new_consumer(tg)
            self._start_time = self._window_start_time = time.monotonic()

            await asyncio.sleep(self.settings.initial_grace_period_seconds)

            while True:
                if self.is_over_target_duration():
                    # We overshot our target, scale as much as we can and exit.
                    self._add_max_consumers(tg)
                    break

                if self.is_at_max_consumers() or self.done():
                    # We are done, or can't scale anymore, exit.
                    # TODO: If/when we support scaling down, then we must not exit
                    # at max consumers, only when done.
                    break

                self.poll()

                consumers_delta = self._calculate_consumers_delta()

                if consumers_delta <= 0:
                    # TODO: Support scaling *down* number of consumers?
                    continue

                for _ in range(consumers_delta):
                    self._add_new_consumer(tg)

                await self._wait_poll_delay()

        return self.result

    def is_at_max_consumers(self) -> bool:
        """Whether this is already at max consumers."""
        return self.number_of_consumers == self.settings.max_consumers

    def is_over_target_duration(self) -> bool:
        """Whether this is already past the target duration for the export."""
        return self.time_elapsed >= self.settings.target_duration_seconds

    def poll(self) -> None:
        """Poll consumers to refresh internal tracking metrics."""
        if self._window_counter == self.settings.tracking_window_size:
            self._window_counter = 0
            self.bytes_exported_window = 0
            self.time_elapsed_window = 0

        now = time.monotonic()
        current_total_bytes_exported = sum(map(_GET_TOTAL_RECORD_BATCH_BYTES_COUNT, self.consumers))
        bytes_exported_since_last_poll = current_total_bytes_exported - self.bytes_exported

        self.time_elapsed = now - self.start_time
        self.bytes_exported = current_total_bytes_exported
        self.bytes_exported_window += bytes_exported_since_last_poll
        self.time_elapsed_window = now - self.window_start_time

        if self._window_counter == self.settings.tracking_window_size - 1:
            # NOTE: Counter increments by 1 right after so the next poll falls in a new window.
            # The time elapsed for that new window starts in the previous poll, i.e. now.
            self._window_start_time = now
        self._window_counter += 1
        self._last_poll_time = now

    def _calculate_consumers_delta(self) -> int:
        """Calculate the delta between consumers needed and current number of consumers.

        That is, the number of consumers needed to finish within the time left until
        hitting the configured ``settings.target_duration_seconds``.

        This uses the consumption rate of the last window, as configured by
        ``settings.tracking_window_size``, and assumes a constant rate for all consumers
        moving forward. With this number, we can simply extrapolate and figure out which
        number of consumers we should have and compare it against the number of
        consumers currently in the group.

        The result will be rounded to the closest integer, as there is no such thing as
        fractional consumers. Moreover, the result will be bounded such that the delta
        never puts us above ``settings.max_consumers`` or below
        ``settings.min_consumers``.
        """

        if not self.bytes_exported or not self.bytes_exported_per_second_window:
            # We have not started or don't have any data to update our estimates
            return 0

        bytes_left = self.settings.total_size_bytes - self.bytes_exported
        time_left = self.settings.target_duration_seconds - self.time_elapsed
        target_bytes_consumption_rate = bytes_left / time_left

        bytes_consumption_rate_per_consumer = self.bytes_exported_per_second_window / self.number_of_consumers
        number_of_consumers_needed = int(round(target_bytes_consumption_rate / bytes_consumption_rate_per_consumer))

        if number_of_consumers_needed >= self.settings.max_consumers:
            return self.settings.max_consumers - self.number_of_consumers
        elif number_of_consumers_needed <= self.settings.min_consumers:
            return self.settings.min_consumers - self.number_of_consumers
        else:
            return number_of_consumers_needed - self.number_of_consumers

    async def _wait_poll_delay(self):
        """Wait for configured ``settings.poll_delay_seconds``.

        This is abstracted mostly so that it can be overridden in tests to control run
        loop iterations.
        """
        await asyncio.sleep(self.settings.poll_delay_seconds)

    def _add_max_consumers(self, task_group: asyncio.TaskGroup) -> None:
        """Add as many new consumers to the group as possible."""
        while not self.number_of_consumers == self.settings.max_consumers:
            self._add_new_consumer(task_group)

    def _add_new_consumer(self, task_group: asyncio.TaskGroup) -> None:
        """Build a new consumer, start it, and add it to the group."""
        consumer = self.build_consumer()
        coro = self.run_consumer(consumer)

        # KLUDGE: We have to schedule the task "manually" so that the consumer tracks
        # it. We can't simply call ``Consumer.start()`` because then we would need the
        # group to pass all the arguments that ``start()`` requires, which are a lot.
        # This is also why this protocol requires two methods instead of one.
        # TODO: We should clean up the signature of ``start()`` so that consumers can
        # start without any arguments. But in the meantime, this minimizes the blast
        # radius, and allows us to adopt groups progressively.
        consumer._schedule_coro(coro, task_group, name=f"consumer-{self.number_of_consumers + 1}")
        consumer.task.add_done_callback(self._accumulate_results)

        self.consumers.add(consumer)

    def _accumulate_results(self, task: ConsumerTask) -> None:
        """Accumulate results from successfully completed consumer tasks."""
        assert task.done()

        if task.cancelled() or task.exception() is not None:
            # No results to accumulate
            return

        result = task.result()

        if result.records_completed is not None:
            self.records_completed += result.records_completed

        if result.bytes_exported is not None:
            self.bytes_exported += result.bytes_exported

        if result.error is not None:
            # TODO: Consolidate errors of the same type into one
            if not isinstance(result.error, list):
                errors = [result.error]
            else:
                errors = result.error

            self.errors.extend(errors)
