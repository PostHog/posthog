import abc
import asyncio
import collections.abc
import datetime as dt
import operator
import typing
import uuid

import pyarrow as pa
import structlog
import temporalio.common
from django.conf import settings

from posthog.temporal.batch_exports.heartbeat import BatchExportRangeHeartbeatDetails
from posthog.temporal.batch_exports.metrics import (
    get_bytes_exported_metric,
    get_rows_exported_metric,
)
from posthog.temporal.batch_exports.sql import (
    SELECT_FROM_EVENTS_VIEW,
    SELECT_FROM_EVENTS_VIEW_BACKFILL,
    SELECT_FROM_EVENTS_VIEW_RECENT,
    SELECT_FROM_EVENTS_VIEW_UNBOUNDED,
    SELECT_FROM_PERSONS_VIEW,
    SELECT_FROM_PERSONS_VIEW_BACKFILL,
    SELECT_FROM_PERSONS_VIEW_BACKFILL_NEW,
    SELECT_FROM_PERSONS_VIEW_NEW,
)
from posthog.temporal.batch_exports.temporary_file import (
    BatchExportTemporaryFile,
    BytesSinceLastFlush,
    DateRange,
    FlushCounter,
    IsLast,
    RecordsSinceLastFlush,
    WriterFormat,
    get_batch_export_writer,
)
from posthog.temporal.batch_exports.utils import (
    cast_record_batch_json_columns,
    cast_record_batch_schema_json_columns,
)
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger()


class RecordBatchQueue(asyncio.Queue):
    """A queue of pyarrow RecordBatch instances limited by bytes."""

    def __init__(self, max_size_bytes: int = 0) -> None:
        super().__init__(maxsize=max_size_bytes)
        self._bytes_size = 0
        self._schema_set = asyncio.Event()
        self.record_batch_schema = None
        # This is set by `asyncio.Queue.__init__` calling `_init`
        self._queue: collections.deque

    def _get(self) -> pa.RecordBatch:
        """Override parent `_get` to keep track of bytes."""
        item = self._queue.popleft()
        self._bytes_size -= item.get_total_buffer_size()
        return item

    def _put(self, item: pa.RecordBatch) -> None:
        """Override parent `_put` to keep track of bytes."""
        self._bytes_size += item.get_total_buffer_size()

        if not self._schema_set.is_set():
            self.set_schema(item)

        self._queue.append(item)

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
        return self.record_batch_schema

    def qsize(self) -> int:
        """Size in bytes of record batches in the queue.

        This is used to determine when the queue is full, so it returns the
        number of bytes.
        """
        return self._bytes_size


class TaskNotDoneError(Exception):
    """Raised when a task that should be done, isn't."""

    def __init__(self, task: str):
        super().__init__(f"Expected task '{task}' to be done by now")


class RecordBatchTaskError(Exception):
    """Raised when an error occurs during consumption of record batches."""

    def __init__(self):
        super().__init__("The record batch consumer encountered an error during execution")


async def raise_on_task_failure(task: asyncio.Task) -> None:
    """Raise `RecordBatchProducerError` if a producer task failed.

    We will also raise a `TaskNotDone` if the producer is not done, as this
    should only be called after producer is done to check its exception.
    """
    if not task.done():
        raise TaskNotDoneError(task.get_name())

    if task.exception() is None:
        return

    exc = task.exception()
    await logger.aexception("%s task failed", task.get_name(), exc_info=exc)
    raise RecordBatchTaskError() from exc


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


class Consumer:
    """Async consumer for batch exports.

    Attributes:
        flush_start_event: Event set when this consumer's flush method starts.
        heartbeater: A batch export's heartbeater used for tracking progress.
        heartbeat_details: A batch export's heartbeat details passed to the
            heartbeater used for tracking progress.
        data_interval_start: The beginning of the batch export period.
        logger: Provided consumer logger.
    """

    def __init__(
        self,
        heartbeater: Heartbeater,
        heartbeat_details: BatchExportRangeHeartbeatDetails,
        data_interval_start: dt.datetime | str | None,
        writer_format: WriterFormat,
    ):
        self.flush_start_event = asyncio.Event()
        self.heartbeater = heartbeater
        self.heartbeat_details = heartbeat_details
        self.data_interval_start = data_interval_start
        self.writer_format = writer_format
        self.logger = logger

    @property
    def rows_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the rows exported metric counter."""
        return get_rows_exported_metric()

    @property
    def bytes_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the bytes exported metric counter."""
        return get_bytes_exported_metric()

    @abc.abstractmethod
    async def flush(
        self,
        batch_export_file: BatchExportTemporaryFile,
        records_since_last_flush: RecordsSinceLastFlush,
        bytes_since_last_flush: BytesSinceLastFlush,
        flush_counter: FlushCounter,
        last_date_range: DateRange,
        is_last: IsLast,
        error: Exception | None,
    ):
        """Method called on reaching `max_bytes` when running the consumer.

        Each batch export should override this method with their own implementation
        of flushing, as each destination will have different requirements for
        flushing data.

        Arguments:
            batch_export_file: The temporary file containing data to flush.
            records_since_last_flush: How many records were written in the temporary
                file.
            bytes_since_last_flush: How many records were written in the temporary
                file.
            error: If any error occurs while writing the temporary file.
        """
        pass

    async def start(
        self,
        queue: RecordBatchQueue,
        producer_task: asyncio.Task,
        max_bytes: int,
        schema: pa.Schema,
        json_columns: collections.abc.Sequence[str],
        multiple_files: bool = False,
        include_inserted_at: bool = False,
        max_file_size_bytes: int = 0,
        **kwargs,
    ) -> int:
        """Start consuming record batches from queue.

        Record batches will be written to a temporary file defined by `writer_format`
        and the file will be flushed upon reaching at least `max_bytes`.

        Callers can control whether a new file is created for each flush or whether we
        continue flushing to the same file by setting `multiple_files`. File data is
        reset regardless, so this is not meant to impact total file size, but rather
        to control whether we are exporting a single large file in multiple parts, or
        multiple files that must each individually be valid.

        Returns:
            Total number of records in all consumed record batches.
        """
        await logger.adebug("Starting record batch consumer")

        schema = cast_record_batch_schema_json_columns(schema, json_columns=json_columns)
        writer = get_batch_export_writer(self.writer_format, self.flush, schema=schema, max_bytes=max_bytes, **kwargs)

        record_batches_count = 0
        records_count = 0

        await self.logger.adebug("Starting record batch writing loop")

        writer._batch_export_file = await asyncio.to_thread(writer.create_temporary_file)

        async for record_batch in self.generate_record_batches_from_queue(queue, producer_task):
            record_batches_count += 1
            record_batch = cast_record_batch_json_columns(record_batch, json_columns=json_columns)

            await writer.write_record_batch(record_batch, flush=False, include_inserted_at=include_inserted_at)

            if writer.should_flush():
                records_count += writer.records_since_last_flush

                if multiple_files:
                    await writer.hard_flush()
                elif max_file_size_bytes > 0 and writer.bytes_total >= max_file_size_bytes:
                    await writer.hard_flush()
                else:
                    await writer.flush()

                for _ in range(record_batches_count):
                    queue.task_done()
                record_batches_count = 0

        records_count += writer.records_since_last_flush
        await writer.close_temporary_file()
        await self.close()

        await self.logger.adebug("Consumed %s records", records_count)
        self.heartbeater.set_from_heartbeat_details(self.heartbeat_details)
        return records_count

    async def close(self):
        """This method can be overridden by subclasses to perform any additional cleanup."""
        pass

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
                    await self.logger.adebug(
                        "Empty queue with no more events being produced, closing writer loop and flushing"
                    )
                    break
                else:
                    await asyncio.sleep(0)
                    continue

            yield record_batch


class RecordBatchConsumerRetryableExceptionGroup(ExceptionGroup):
    """ExceptionGroup raised when at least one task fails with a retryable exception."""

    def derive(self, excs):
        return RecordBatchConsumerRetryableExceptionGroup(self.message, excs)


class RecordBatchConsumerNonRetryableExceptionGroup(ExceptionGroup):
    """ExceptionGroup raised when all tasks fail with non-retryable exception."""

    def derive(self, excs):
        return RecordBatchConsumerNonRetryableExceptionGroup(self.message, excs)


async def run_consumer_loop(
    queue: RecordBatchQueue,
    consumer_cls: type[Consumer],
    producer_task: asyncio.Task,
    heartbeater: Heartbeater,
    heartbeat_details: BatchExportRangeHeartbeatDetails,
    data_interval_end: dt.datetime | str,
    data_interval_start: dt.datetime | str | None,
    schema: pa.Schema,
    writer_format: WriterFormat,
    max_bytes: int,
    json_columns: collections.abc.Sequence[str] = ("properties", "person_properties", "set", "set_once"),
    writer_file_kwargs: collections.abc.Mapping[str, typing.Any] | None = None,
    multiple_files: bool = False,
    include_inserted_at: bool = False,
    max_file_size_bytes: int = 0,
    **kwargs,
) -> int:
    """Run record batch consumers in a loop.

    When a consumer starts flushing, a new consumer will be started, and so on in
    a loop. Once there is nothing left to consumer from the `RecordBatchQueue`, no
    more consumers will be started, and any pending consumers are awaited.

    NOTE: We're starting to include the `_inserted_at` column in the record
    batches, one destination at a time, so once we've added it to all
    destinations, we can remove the `include_inserted_at` argument.

    Returns:
        Number of records exported. Not the number of record batches, but the
        number of records in all record batches.

    Raises:
        RecordBatchConsumerRetryableExceptionGroup: When at least one consumer task
            fails with a retryable error.
        RecordBatchConsumerNonRetryableExceptionGroup: When all consumer tasks fail
            with non-retryable errors.
    """
    consumer_tasks_pending: set[asyncio.Task] = set()
    consumer_tasks_done = set()
    consumer_number = 0
    records_completed = 0

    def consumer_done_callback(task: asyncio.Task):
        nonlocal records_completed
        nonlocal consumer_tasks_done
        nonlocal consumer_tasks_pending

        try:
            records_completed += task.result()
        except:
            pass

        consumer_tasks_pending.remove(task)
        consumer_tasks_done.add(task)

    await logger.adebug("Starting record batch consumer loop")

    consumer = consumer_cls(heartbeater, heartbeat_details, data_interval_start, writer_format, **kwargs)
    consumer_task = asyncio.create_task(
        consumer.start(
            queue=queue,
            producer_task=producer_task,
            max_bytes=max_bytes,
            schema=schema,
            json_columns=json_columns,
            multiple_files=multiple_files,
            include_inserted_at=include_inserted_at,
            max_file_size_bytes=max_file_size_bytes,
            **writer_file_kwargs or {},
        ),
        name=f"record_batch_consumer_{consumer_number}",
    )
    consumer_tasks_pending.add(consumer_task)
    consumer_task.add_done_callback(consumer_done_callback)
    consumer_number += 1

    await asyncio.wait([consumer_task])

    if consumer_task.done():
        consumer_task_exception = consumer_task.exception()

        if consumer_task_exception is not None:
            raise consumer_task_exception

    await logger.adebug("Finished consuming record batches")

    await raise_on_task_failure(producer_task)
    await logger.adebug("Successfully consumed all record batches")

    heartbeat_details.complete_done_ranges(data_interval_end)
    heartbeater.set_from_heartbeat_details(heartbeat_details)

    return records_completed


class BatchExportField(typing.TypedDict):
    """A field to be queried from ClickHouse.

    Attributes:
        expression: A ClickHouse SQL expression that declares the field required.
        alias: An alias to apply to the expression (after an 'AS' keyword).
    """

    expression: str
    alias: str


def default_fields() -> list[BatchExportField]:
    """Return list of default batch export Fields."""
    return [
        BatchExportField(expression="uuid", alias="uuid"),
        BatchExportField(expression="team_id", alias="team_id"),
        BatchExportField(expression="timestamp", alias="timestamp"),
        BatchExportField(expression="_inserted_at", alias="_inserted_at"),
        BatchExportField(expression="created_at", alias="created_at"),
        BatchExportField(expression="event", alias="event"),
        BatchExportField(expression="properties", alias="properties"),
        BatchExportField(expression="distinct_id", alias="distinct_id"),
        BatchExportField(expression="set", alias="set"),
        BatchExportField(
            expression="set_once",
            alias="set_once",
        ),
    ]


class Producer:
    """Async producer for batch exports.

    Attributes:
        clickhouse_client: ClickHouse client used to produce RecordBatches.
        _task: Used to keep track of producer background task.
    """

    def __init__(self, clickhouse_client: ClickHouseClient):
        self.clickhouse_client = clickhouse_client
        self._task: asyncio.Task | None = None

    @property
    def task(self) -> asyncio.Task:
        if self._task is None:
            raise ValueError("Producer task is not initialized, have you called `Producer.start()`?")
        return self._task

    def start(
        self,
        queue: RecordBatchQueue,
        model_name: str,
        is_backfill: bool,
        team_id: int,
        full_range: tuple[dt.datetime | None, dt.datetime],
        done_ranges: list[tuple[dt.datetime, dt.datetime]],
        fields: list[BatchExportField] | None = None,
        destination_default_fields: list[BatchExportField] | None = None,
        use_latest_schema: bool = False,
        **parameters,
    ) -> asyncio.Task:
        if fields is None:
            if destination_default_fields is None:
                fields = default_fields()
            else:
                fields = destination_default_fields

        if model_name == "persons":
            if is_backfill and full_range[0] is None:
                if use_latest_schema:
                    query = SELECT_FROM_PERSONS_VIEW_BACKFILL_NEW
                else:
                    query = SELECT_FROM_PERSONS_VIEW_BACKFILL
            else:
                if use_latest_schema:
                    query = SELECT_FROM_PERSONS_VIEW_NEW
                else:
                    query = SELECT_FROM_PERSONS_VIEW
        else:
            if parameters.get("exclude_events", None):
                parameters["exclude_events"] = list(parameters["exclude_events"])
            else:
                parameters["exclude_events"] = []

            if parameters.get("include_events", None):
                parameters["include_events"] = list(parameters["include_events"])
            else:
                parameters["include_events"] = []

            start_at, end_at = full_range

            if start_at:
                is_5_min_batch_export = (end_at - start_at) == dt.timedelta(seconds=300)
            else:
                is_5_min_batch_export = False

            if is_5_min_batch_export and not is_backfill:
                query_template = SELECT_FROM_EVENTS_VIEW_RECENT
            elif str(team_id) in settings.UNCONSTRAINED_TIMESTAMP_TEAM_IDS:
                query_template = SELECT_FROM_EVENTS_VIEW_UNBOUNDED
            elif is_backfill:
                query_template = SELECT_FROM_EVENTS_VIEW_BACKFILL
            else:
                query_template = SELECT_FROM_EVENTS_VIEW
                lookback_days = settings.OVERRIDE_TIMESTAMP_TEAM_IDS.get(
                    team_id, settings.DEFAULT_TIMESTAMP_LOOKBACK_DAYS
                )
                parameters["lookback_days"] = lookback_days

            if "_inserted_at" not in [field["alias"] for field in fields]:
                control_fields = [BatchExportField(expression="_inserted_at", alias="_inserted_at")]
            else:
                control_fields = []

            query_fields = ",".join(f"{field['expression']} AS {field['alias']}" for field in fields + control_fields)

            query = query_template.substitute(fields=query_fields)

        parameters["team_id"] = team_id

        extra_query_parameters = parameters.pop("extra_query_parameters", {}) or {}
        parameters = {**parameters, **extra_query_parameters}

        self._task = asyncio.create_task(
            self.produce_batch_export_record_batches_from_range(
                query=query, full_range=full_range, done_ranges=done_ranges, queue=queue, query_parameters=parameters
            ),
            name="record_batch_producer",
        )

        return self.task

    async def produce_batch_export_record_batches_from_range(
        self,
        query: str,
        full_range: tuple[dt.datetime | None, dt.datetime],
        done_ranges: collections.abc.Sequence[tuple[dt.datetime, dt.datetime]],
        queue: RecordBatchQueue,
        query_parameters: dict[str, typing.Any],
    ):
        for interval_start, interval_end in generate_query_ranges(full_range, done_ranges):
            if interval_start is not None:
                query_parameters["interval_start"] = interval_start.strftime("%Y-%m-%d %H:%M:%S.%f")
            query_parameters["interval_end"] = interval_end.strftime("%Y-%m-%d %H:%M:%S.%f")
            query_id = uuid.uuid4()

            await self.clickhouse_client.aproduce_query_as_arrow_record_batches(
                query, queue=queue, query_parameters=query_parameters, query_id=str(query_id)
            )


def generate_query_ranges(
    remaining_range: tuple[dt.datetime | None, dt.datetime],
    done_ranges: collections.abc.Sequence[tuple[dt.datetime, dt.datetime]],
) -> typing.Iterator[tuple[dt.datetime | None, dt.datetime]]:
    """Recursively yield ranges of dates that need to be queried.

    There are essentially 3 scenarios we are expecting:
    1. The batch export just started, so we expect `done_ranges` to be an empty
       list, and thus should return the `remaining_range`.
    2. The batch export crashed mid-execution, so we have some `done_ranges` that
       do not completely add up to the full range. In this case we need to yield
       ranges in between all the done ones.
    3. The batch export crashed right after we finish, so we have a full list of
       `done_ranges` adding up to the `remaining_range`. In this case we should not
       yield anything.

    Case 1 is fairly trivial and we can simply return `remaining_range` if we get
    an empty `done_ranges`.

    Case 2 is more complicated and we can expect that the ranges produced by this
    function will lead to duplicate events selected, as our batch export query is
    inclusive in the lower bound. Since multiple rows may have the same
    `inserted_at` we cannot simply skip an `inserted_at` value, as there may be a
    row that hasn't been exported as it with the same `inserted_at` as a row that
    has been exported. So this function will return ranges with `inserted_at`
    values that were already exported for at least one event. Ideally, this is
    *only* one event, but we can never be certain.
    """
    if len(done_ranges) == 0:
        yield remaining_range
        return

    epoch = dt.datetime.fromtimestamp(0, tz=dt.UTC)
    list_done_ranges: list[tuple[dt.datetime, dt.datetime]] = list(done_ranges)

    list_done_ranges.sort(key=operator.itemgetter(0))

    while True:
        try:
            next_range: tuple[dt.datetime | None, dt.datetime] = list_done_ranges.pop(0)
        except IndexError:
            if remaining_range[0] != remaining_range[1]:
                # If they were equal it would mean we have finished.
                yield remaining_range

            return
        else:
            candidate_end_at = next_range[0] if next_range[0] is not None else epoch

        candidate_start_at = remaining_range[0]
        remaining_range = (next_range[1], remaining_range[1])

        if candidate_start_at is not None and candidate_start_at >= candidate_end_at:
            # We have landed within a done range.
            continue

        if candidate_start_at is None and candidate_end_at == epoch:
            # We have landed within the first done range of a backfill.
            continue

        yield (candidate_start_at, candidate_end_at)
