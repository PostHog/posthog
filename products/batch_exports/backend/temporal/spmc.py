import abc
import asyncio
import collections.abc
import datetime as dt
import math
import operator
import typing
import uuid

import pyarrow as pa
import temporalio.common
from django.conf import settings

from posthog.batch_exports.service import (
    BackfillDetails,
    BatchExportModel,
    BatchExportSchema,
)
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.property import property_to_expr
from posthog.models import Team
from posthog.schema import EventPropertyFilter, HogQLQueryModifiers, MaterializationMode
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_external_logger, get_logger
from products.batch_exports.backend.temporal import sql
from products.batch_exports.backend.temporal.heartbeat import (
    BatchExportRangeHeartbeatDetails,
    DateRange,
)
from products.batch_exports.backend.temporal.metrics import (
    get_bytes_exported_metric,
    get_rows_exported_metric,
)
from products.batch_exports.backend.temporal.sql import (
    SELECT_FROM_DISTRIBUTED_EVENTS_RECENT,
    SELECT_FROM_EVENTS_VIEW,
    SELECT_FROM_EVENTS_VIEW_BACKFILL,
    SELECT_FROM_EVENTS_VIEW_RECENT,
    SELECT_FROM_EVENTS_VIEW_UNBOUNDED,
    SELECT_FROM_PERSONS,
    SELECT_FROM_PERSONS_BACKFILL,
)
from products.batch_exports.backend.temporal.temporary_file import (
    BatchExportTemporaryFile,
    BytesSinceLastFlush,
    FlushCounter,
    IsLast,
    RecordsSinceLastFlush,
    WriterFormat,
    get_batch_export_writer,
)
from products.batch_exports.backend.temporal.transformer import get_stream_transformer
from products.batch_exports.backend.temporal.utils import (
    cast_record_batch_json_columns,
    cast_record_batch_schema_json_columns,
)

LOGGER = get_logger(__name__)
EXTERNAL_LOGGER = get_external_logger()


class RecordBatchQueue(asyncio.Queue):
    """A queue of pyarrow RecordBatch instances limited by bytes."""

    def __init__(self, max_size_bytes: int = 0) -> None:
        super().__init__(maxsize=max_size_bytes)
        self._bytes_size = 0
        self._schema_set = asyncio.Event()
        self.record_batch_schema: pa.Schema | None = None
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
        assert self.record_batch_schema is not None
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

    def __init__(self, error_details: str):
        super().__init__(f"Record batch consumer encountered an error: {error_details}")


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


class Consumer:
    """Async consumer for batch exports.

    Attributes:
        flush_start_event: Event set when this consumer's flush method starts.
        heartbeater: A batch export's heartbeater used for tracking progress.
        heartbeat_details: A batch export's heartbeat details passed to the
            heartbeater used for tracking progress.
        data_interval_start: The beginning of the batch export period.
        logger: Internal consumer logger.
    """

    def __init__(
        self,
        heartbeater: Heartbeater,
        heartbeat_details: BatchExportRangeHeartbeatDetails,
        data_interval_start: dt.datetime | str | None,
        data_interval_end: dt.datetime | str,
        writer_format: WriterFormat,
    ):
        self.flush_start_event = asyncio.Event()
        self.heartbeater = heartbeater
        self.heartbeat_details = heartbeat_details
        self.data_interval_start = data_interval_start
        self.data_interval_end = data_interval_end
        self.writer_format = writer_format
        self.logger = LOGGER.bind(writer_format=writer_format)
        self.external_logger = EXTERNAL_LOGGER.bind(writer_format=writer_format)

    @property
    def rows_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the rows exported metric counter."""
        return get_rows_exported_metric()

    @property
    def bytes_exported_counter(self) -> temporalio.common.MetricCounter:
        """Access the bytes exported metric counter."""
        return get_bytes_exported_metric()

    def create_consumer_task(
        self,
        tg: asyncio.TaskGroup,
        queue: RecordBatchQueue,
        producer_task: asyncio.Task,
        max_bytes: int,
        schema: pa.Schema,
        json_columns: collections.abc.Sequence[str],
        multiple_files: bool = False,
        include_inserted_at: bool = False,
        task_name: str = "record_batch_consumer",
        max_file_size_bytes: int = 0,
        **kwargs,
    ) -> asyncio.Task:
        """Create a record batch consumer task."""
        self.logger.debug("Starting consumer task '%s'", task_name)

        consumer_task = tg.create_task(
            self.start(
                queue=queue,
                producer_task=producer_task,
                max_bytes=max_bytes,
                schema=schema,
                json_columns=json_columns,
                multiple_files=multiple_files,
                include_inserted_at=include_inserted_at,
                max_file_size_bytes=max_file_size_bytes,
                **kwargs,
            ),
            name=task_name,
        )
        return consumer_task

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
        self.logger = self.logger.bind(producer_task=producer_task.get_name())
        schema = cast_record_batch_schema_json_columns(schema, json_columns=json_columns)
        writer = get_batch_export_writer(
            self.writer_format,
            self.flush,
            schema=schema,
            max_bytes=max_bytes,
            max_file_size_bytes=max_file_size_bytes,
            **kwargs,
        )

        record_batches_count = 0
        record_batches_count_total = 0
        records_count = 0

        self.logger.info("Consuming record batches directly from ClickHouse")

        writer._batch_export_file = await asyncio.to_thread(writer.create_temporary_file)

        async for record_batch in self.generate_record_batches_from_queue(queue, producer_task):
            record_batches_count += 1
            record_batches_count_total += 1
            record_batch = cast_record_batch_json_columns(record_batch, json_columns=json_columns)

            await writer.write_record_batch(record_batch, flush=False, include_inserted_at=include_inserted_at)

            if writer.should_flush() or writer.should_hard_flush():
                self.logger.info(
                    "Flushing %d records from %d record batches", writer.records_since_last_flush, record_batches_count
                )

                records_count += writer.records_since_last_flush

                if multiple_files or writer.should_hard_flush():
                    await writer.hard_flush()
                else:
                    await writer.flush()

                for _ in range(record_batches_count):
                    queue.task_done()
                record_batches_count = 0

            self.heartbeater.set_from_heartbeat_details(self.heartbeat_details)

        records_count += writer.records_since_last_flush

        self.logger.info(
            "Finished consuming %d records from %d record batches, will flush any pending data",
            records_count,
            record_batches_count_total,
        )

        await writer.close_temporary_file()
        await self.close()

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
                    self.logger.debug(
                        "Empty queue with no more events being produced, closing writer loop and flushing"
                    )
                    break
                else:
                    await asyncio.sleep(0)
                    continue

            yield record_batch

    def complete_heartbeat(self):
        """Complete this consumer's heartbeats."""
        self.heartbeat_details.complete_done_ranges(self.data_interval_end)
        self.heartbeater.set_from_heartbeat_details(self.heartbeat_details)


class RecordBatchConsumerRetryableExceptionGroup(ExceptionGroup):
    """ExceptionGroup raised when at least one task fails with a retryable exception."""

    def derive(self, excs):
        return RecordBatchConsumerRetryableExceptionGroup(self.message, excs)


class RecordBatchConsumerNonRetryableExceptionGroup(ExceptionGroup):
    """ExceptionGroup raised when all tasks fail with non-retryable exception."""

    def derive(self, excs):
        return RecordBatchConsumerNonRetryableExceptionGroup(self.message, excs)


async def run_consumer(
    queue: RecordBatchQueue,
    consumer: Consumer,
    producer_task: asyncio.Task,
    max_bytes: int,
    schema: pa.Schema,
    json_columns: collections.abc.Sequence[str] = ("properties", "person_properties", "set", "set_once"),
    multiple_files: bool = False,
    writer_file_kwargs: collections.abc.Mapping[str, typing.Any] | None = None,
    include_inserted_at: bool = False,
    max_file_size_bytes: int = 0,
    **kwargs,
) -> int:
    """Run one record batch consumer.

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
    records_completed = 0

    def consumer_done_callback(task: asyncio.Task):
        nonlocal records_completed
        nonlocal consumer_tasks_done
        nonlocal consumer_tasks_pending

        if task.cancelled():
            LOGGER.debug("Record batch consumer task cancelled")

        try:
            records_completed += task.result()
        except:
            pass

        consumer_tasks_pending.remove(task)
        consumer_tasks_done.add(task)

    # We use a TaskGroup to ensure that if the activity is cancelled, this is propagated to all pending tasks.
    try:
        async with asyncio.TaskGroup() as tg:
            consumer_task = consumer.create_consumer_task(
                tg=tg,
                queue=queue,
                producer_task=producer_task,
                max_bytes=max_bytes,
                schema=schema,
                json_columns=json_columns,
                multiple_files=multiple_files,
                include_inserted_at=include_inserted_at,
                max_file_size_bytes=max_file_size_bytes,
                **writer_file_kwargs or {},
            )
            consumer_task.add_done_callback(consumer_done_callback)
            consumer_tasks_pending.add(consumer_task)
    except Exception:
        if consumer_task.done():
            consumer_task_exception = consumer_task.exception()

            if consumer_task_exception is not None:
                raise consumer_task_exception

    await raise_on_task_failure(producer_task)
    LOGGER.debug("Successfully finished record batch consumer")

    consumer.complete_heartbeat()

    return records_completed


Query = str
QueryParameters = dict[str, typing.Any]
BatchExportDateRange = tuple[dt.datetime | None, dt.datetime]


class RecordBatchModel(abc.ABC):
    """Base class for models that can be produced as record batches."""

    def __init__(self, team_id: int):
        self.team_id = team_id

    async def get_hogql_context(self, team_id: int) -> HogQLContext:
        """Return a HogQLContext to generate a ClickHouse query."""
        team = await Team.objects.aget(id=team_id)
        context = HogQLContext(
            team=team,
            team_id=team.id,
            enable_select_queries=True,
            limit_top_select=False,
        )
        context.database = await database_sync_to_async(create_hogql_database)(team=team, modifiers=context.modifiers)

        return context

    @abc.abstractmethod
    async def as_query_with_parameters(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime
    ) -> tuple[Query, QueryParameters]:
        """Produce a printed query and any necessary ClickHouse query parameters."""
        raise NotImplementedError


class SessionsRecordBatchModel(RecordBatchModel):
    """A model to produce record batches from the sessions table.

    Attributes:
       team_id: The ID of the team we are producing records for.
    """

    def __init__(self, team_id: int):
        super().__init__(team_id)

    def get_hogql_query(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime
    ) -> ast.SelectQuery:
        """Return the HogQLQuery used for the sessions model."""
        hogql_query = sql.SELECT_FROM_SESSIONS_HOGQL

        where_and = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["sessions", "team_id"]),
                    right=ast.Constant(value=self.team_id),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["_inserted_at"]),
                    right=ast.Constant(value=data_interval_end),
                ),
                # include $end_timestamp because hogql uses this to add a where clause to the inner query
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["$end_timestamp"]),
                    right=ast.Constant(value=data_interval_end),
                ),
            ]
        )
        if data_interval_start is not None:
            where_and.exprs.extend(
                [
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=ast.Field(chain=["_inserted_at"]),
                        right=ast.Constant(value=data_interval_start),
                    ),
                    # include $end_timestamp because hogql uses this to add a where clause to the inner query
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=ast.Field(chain=["$end_timestamp"]),
                        right=ast.Constant(value=data_interval_start),
                    ),
                ]
            )

        hogql_query.where = where_and

        return hogql_query

    async def as_query_with_parameters(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime
    ) -> tuple[Query, QueryParameters]:
        """Produce a printed query and any necessary ClickHouse query parameters."""
        hogql_query = self.get_hogql_query(data_interval_start, data_interval_end)
        context = await self.get_hogql_context(self.team_id)

        prepared_hogql_query = await database_sync_to_async(prepare_ast_for_printing)(
            hogql_query, context=context, dialect="clickhouse", stack=[]
        )
        assert prepared_hogql_query is not None
        context.output_format = "ArrowStream"
        printed = print_prepared_ast(
            prepared_hogql_query,
            context=context,
            dialect="clickhouse",
            stack=[],
        )
        return printed, context.values


def resolve_batch_exports_model(
    team_id: int,
    batch_export_model: BatchExportModel | None = None,
    batch_export_schema: BatchExportSchema | None = None,
):
    """Resolve which model and model parameters to use for a batch export.

    This function exists to isolate a lot of repetitive checks that deal with deprecated
    and new parameters. Eventually, once everything is a `RecordBatchModel`, this could
    be removed.
    """
    model: BatchExportModel | BatchExportSchema | None = None
    record_batch_model = None
    if batch_export_schema is None:
        model = batch_export_model
        if model is not None:
            model_name = model.name
            extra_query_parameters = model.schema["values"] if model.schema is not None else None
            fields = model.schema["fields"] if model.schema is not None else None
            filters = model.filters

            if model_name == "sessions":
                record_batch_model = SessionsRecordBatchModel(team_id)
        else:
            model_name = "events"
            extra_query_parameters = None
            fields = None
            filters = None
    else:
        model = batch_export_schema
        model_name = "custom"
        extra_query_parameters = model["values"] if model is not None else {}
        fields = model["fields"] if model is not None else None
        filters = None

    return model, record_batch_model, model_name, fields, filters, extra_query_parameters


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


def is_5_min_batch_export(full_range: tuple[dt.datetime | None, dt.datetime]) -> bool:
    start_at, end_at = full_range
    if start_at:
        return (end_at - start_at) == dt.timedelta(seconds=300)
    return False


def use_distributed_events_recent_table(
    is_backfill: bool, backfill_details: BackfillDetails | None, data_interval_start: dt.datetime | None
) -> bool:
    """We should use the distributed_events_recent table if it's not a backfill (backfill_details is None) or the
    backfill is within the last 6 days.

    We also check the data_interval_start to make sure it's also within the last 6 days (should always be the case for
    realtime batch exports but for tests it may not be the case)

    The events_recent table, and by extension, the distributed_events_recent table, only have event data from the last 7
    days (we use 6 days to give some buffer).
    """

    if (
        not is_backfill
        and data_interval_start
        and data_interval_start > (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=6))
    ):
        return True

    backfill_start_at = None
    if backfill_details and backfill_details.start_at:
        backfill_start_at = dt.datetime.fromisoformat(backfill_details.start_at)
    if backfill_start_at and backfill_start_at > (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=6)):
        return True

    return False


class Producer:
    """Async producer for batch exports.

    Attributes:
        clickhouse_client: ClickHouse client used to produce RecordBatches.
        _task: Used to keep track of producer background task.
    """

    def __init__(self, model: RecordBatchModel | None = None):
        self.model = model
        self.logger = LOGGER.bind()
        self._task: asyncio.Task | None = None

    @property
    def task(self) -> asyncio.Task:
        if self._task is None:
            raise ValueError("Producer task is not initialized, have you called `Producer.start()`?")
        return self._task

    async def start(
        self,
        queue: RecordBatchQueue,
        full_range: tuple[dt.datetime | None, dt.datetime],
        done_ranges: list[tuple[dt.datetime, dt.datetime]],
        is_backfill: bool,
        backfill_details: BackfillDetails | None,
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
        **kwargs,
    ) -> asyncio.Task:
        """Dispatch to one of two implementations, depending on `self.model`."""
        if self.model is not None:
            return await self.start_with_model(
                queue=queue,
                max_record_batch_size_bytes=max_record_batch_size_bytes,
                min_records_per_batch=min_records_per_batch,
                full_range=full_range,
                done_ranges=done_ranges,
            )
        else:
            return await self.start_without_model(
                queue=queue,
                max_record_batch_size_bytes=max_record_batch_size_bytes,
                min_records_per_batch=min_records_per_batch,
                full_range=full_range,
                done_ranges=done_ranges,
                is_backfill=is_backfill,
                backfill_details=backfill_details,
                **kwargs,
            )

    async def start_with_model(
        self,
        queue: RecordBatchQueue,
        full_range: tuple[dt.datetime | None, dt.datetime],
        done_ranges: list[tuple[dt.datetime, dt.datetime]],
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
    ):
        assert self.model is not None

        self._task = asyncio.create_task(
            self.produce_batch_export_record_batches_from_range(
                query_or_model=self.model,
                full_range=full_range,
                done_ranges=done_ranges,
                queue=queue,
                query_parameters={},
                max_record_batch_size_bytes=max_record_batch_size_bytes,
                min_records_per_batch=min_records_per_batch,
                team_id=self.model.team_id,
            ),
            name="record_batch_producer",
        )
        return self._task

    async def start_without_model(
        self,
        queue: RecordBatchQueue,
        model_name: str,
        # TODO: remove once all backfill inputs are migrated
        is_backfill: bool,
        backfill_details: BackfillDetails | None,
        team_id: int,
        full_range: tuple[dt.datetime | None, dt.datetime],
        done_ranges: list[tuple[dt.datetime, dt.datetime]],
        fields: list[BatchExportField] | None = None,
        destination_default_fields: list[BatchExportField] | None = None,
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
        filters: list[dict[str, str | list[str]]] | None = None,
        order_columns: collections.abc.Iterable[str] | None = ("_inserted_at", "event"),
        **parameters,
    ) -> asyncio.Task:
        if fields is None:
            if destination_default_fields is None:
                fields = default_fields()
            else:
                fields = destination_default_fields

        extra_query_parameters = parameters.pop("extra_query_parameters", {}) or {}

        if filters is not None and len(filters) > 0:
            filters_str, extra_query_parameters = await database_sync_to_async(compose_filters_clause)(
                filters, team_id=team_id, values=extra_query_parameters
            )
        else:
            filters_str, extra_query_parameters = "", extra_query_parameters

        # TODO: this can be simplified once all backfill inputs are migrated
        is_backfill = (backfill_details is not None) or is_backfill

        if model_name == "persons":
            if is_backfill and full_range[0] is None:
                query = SELECT_FROM_PERSONS_BACKFILL
            else:
                query = SELECT_FROM_PERSONS
        else:
            if parameters.get("exclude_events", None):
                parameters["exclude_events"] = list(parameters["exclude_events"])
            else:
                parameters["exclude_events"] = []

            if parameters.get("include_events", None):
                parameters["include_events"] = list(parameters["include_events"])
            else:
                parameters["include_events"] = []

            # for 5 min batch exports we query the events_recent table, which is known to have zero replication lag, but
            # may not be able to handle the load from all batch exports
            if is_5_min_batch_export(full_range=full_range) and not is_backfill:
                self.logger.debug("Using events_recent table for 5 min batch export")
                query_template = SELECT_FROM_EVENTS_VIEW_RECENT
            # for other batch exports that should use `events_recent` we use the `distributed_events_recent` table
            # which is a distributed table that sits in front of the `events_recent` table
            elif use_distributed_events_recent_table(
                is_backfill=is_backfill, backfill_details=backfill_details, data_interval_start=full_range[0]
            ):
                self.logger.debug("Using distributed_events_recent table for batch export")
                query_template = SELECT_FROM_DISTRIBUTED_EVENTS_RECENT
            elif str(team_id) in settings.UNCONSTRAINED_TIMESTAMP_TEAM_IDS:
                self.logger.debug("Using events_batch_export_unbounded view for batch export")
                query_template = SELECT_FROM_EVENTS_VIEW_UNBOUNDED
            elif is_backfill:
                self.logger.debug("Using events_batch_export_backfill view for batch export")
                query_template = SELECT_FROM_EVENTS_VIEW_BACKFILL
            else:
                self.logger.debug("Using events_batch_export view for batch export")
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

            if filters_str:
                filters_str = f"AND {filters_str}"

            if str(team_id) in settings.BATCH_EXPORT_ORDERLESS_TEAM_IDS or not order_columns:
                order = ""
            else:
                order = f"ORDER BY {','.join(order_columns)}"

            query = query_template.safe_substitute(fields=query_fields, filters=filters_str, order=order)

        parameters["team_id"] = team_id
        parameters = {**parameters, **extra_query_parameters}

        self._task = asyncio.create_task(
            self.produce_batch_export_record_batches_from_range(
                query_or_model=query,
                full_range=full_range,
                done_ranges=done_ranges,
                queue=queue,
                query_parameters=parameters,
                max_record_batch_size_bytes=max_record_batch_size_bytes,
                min_records_per_batch=min_records_per_batch,
                team_id=team_id,
            ),
            name="record_batch_producer",
        )

        return self.task

    async def produce_batch_export_record_batches_from_range(
        self,
        query_or_model: str | RecordBatchModel,
        full_range: tuple[dt.datetime | None, dt.datetime],
        done_ranges: collections.abc.Sequence[tuple[dt.datetime, dt.datetime]],
        queue: RecordBatchQueue,
        query_parameters: dict[str, typing.Any],
        team_id: int,
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
    ):
        """Produce Arrow record batches for a given date range into `queue`.

        Arguments:
            query: The ClickHouse query used to obtain record batches. The query should be have a
                `FORMAT ArrowStream` clause, although we do not enforce this.
            full_range: The full date range of record batches to produce.
            done_ranges: Date ranges of record batches that have already been exported, and thus
                should be skipped.
            queue: The queue where to produce record batches.
            query_parameters: Additional query parameters.
            team_id: The team ID of the batch export.
            max_record_batch_size_bytes: The max size in bytes of a record batch to insert in `queue`.
                If a record batch is larger than this, `slice_record_batch` will be used to slice it
                into smaller record batches.
            min_records_batch_per_batch: If slicing a record batch, each slice should contain at least
                this number of records.
        """
        clickhouse_url = None
        # 5 min batch exports should query a single node, which is known to have zero replication lag
        if is_5_min_batch_export(full_range=full_range):
            clickhouse_url = settings.CLICKHOUSE_OFFLINE_5MIN_CLUSTER_HOST

        # Data can sometimes take a while to settle, so for 5 min batch exports we wait several seconds just to be safe.
        # For all other batch exports we wait for 1 minute since we're querying the events_recent table using a
        # distributed table and setting `max_replica_delay_for_distributed_queries` to 1 minute
        if is_5_min_batch_export(full_range):
            delta = dt.timedelta(seconds=30)
        else:
            delta = dt.timedelta(minutes=1)
        end_at = full_range[1]
        await wait_for_delta_past_data_interval_end(end_at, delta)

        async with get_client(team_id=team_id, clickhouse_url=clickhouse_url) as client:
            if not await client.is_alive():
                raise ConnectionError("Cannot establish connection to ClickHouse")

            for interval_start, interval_end in generate_query_ranges(full_range, done_ranges):
                if interval_start is not None:
                    query_parameters["interval_start"] = interval_start.strftime("%Y-%m-%d %H:%M:%S.%f")
                query_parameters["interval_end"] = interval_end.strftime("%Y-%m-%d %H:%M:%S.%f")
                query_id = uuid.uuid4()
                self.logger.debug("Executing query with ID '%s'", query_id)

                if isinstance(query_or_model, RecordBatchModel):
                    query, query_parameters = await query_or_model.as_query_with_parameters(
                        interval_start, interval_end
                    )
                else:
                    query = query_or_model

                try:
                    async for record_batch in client.astream_query_as_arrow(
                        query, query_parameters=query_parameters, query_id=str(query_id)
                    ):
                        for record_batch_slice in slice_record_batch(
                            record_batch, max_record_batch_size_bytes, min_records_per_batch
                        ):
                            await queue.put(record_batch_slice)

                except Exception as e:
                    self.logger.exception("Unexpected error occurred while producing record batches", exc_info=e)
                    raise


def slice_record_batch(
    record_batch: pa.RecordBatch, max_record_batch_size_bytes: int = 0, min_records_per_batch: int = 100
) -> typing.Iterator[pa.RecordBatch]:
    """Slice a large Arrow record batch into one or more record batches.

    The underlying call to `pa.RecordBatch.slice` is a zero-copy operation, so the
    memory footprint of slicing is very low, beyond some additional metadata
    required for the slice.

    Arguments:
        record_batch: The record batch to slice.
        max_record_batch_size_bytes: The max size in bytes of a record batch to
            yield. If the provided `record_batch` is larger than this, then it
            will be sliced into multiple record batches.
        min_records_batch_per_batch: Each slice yielded should contain at least
            this number of records.
    """
    if max_record_batch_size_bytes <= 0 or max_record_batch_size_bytes > record_batch.nbytes:
        yield record_batch
        return

    total_rows = record_batch.num_rows
    yielded_rows = 0
    offset = 0
    estimated = _estimate_rows_to_fit_under_max(record_batch, max_record_batch_size_bytes, min_records_per_batch)
    length = total_rows - estimated

    while yielded_rows < total_rows:
        sliced_record_batch = record_batch.slice(offset=offset, length=length)
        current_rows = sliced_record_batch.num_rows

        if sliced_record_batch.nbytes > max_record_batch_size_bytes and current_rows > min_records_per_batch:
            estimated = _estimate_rows_to_fit_under_max(
                sliced_record_batch, max_record_batch_size_bytes, min_records_per_batch
            )
            length -= estimated
            continue

        yield sliced_record_batch

        yielded_rows += current_rows
        offset = offset + length
        length = total_rows - yielded_rows


def _estimate_rows_to_fit_under_max(
    slice: pa.RecordBatch, max_record_batch_size_bytes: int, min_records_per_batch: int
) -> int:
    if slice.nbytes <= max_record_batch_size_bytes or slice.num_rows <= min_records_per_batch:
        return 0

    avg_bytes_per_row = slice.nbytes / slice.num_rows
    bytes_diff = slice.nbytes - max_record_batch_size_bytes
    return max(math.floor(bytes_diff / avg_bytes_per_row), 1)


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


def compose_filters_clause(
    filters: list[dict[str, str | list[str]]],
    team_id: int,
    values: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    """Compose a clause of matching filters for a batch exports query.

    `values` must be set if already replacing other values as otherwise there will
    be collisions with the values returned by this function.

    Arguments:
        filters: A list of serialized HogQL filters.
        team_id: Team we are running for.
        values: HogQL placeholder values already in use.

    Returns:
        A printed string with the ClickHouse SQL clause, and a dictionary
        of placeholder to values to be used as query parameters.
    """
    team = Team.objects.get(id=team_id)
    context = HogQLContext(
        team=team,
        team_id=team.id,
        enable_select_queries=True,
        limit_top_select=False,
        within_non_hogql_query=True,
        values=values or {},
        modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.DISABLED),
    )
    context.database = create_hogql_database(team=team, modifiers=context.modifiers)

    exprs = [property_to_expr(EventPropertyFilter(**filter), team=team) for filter in filters]
    and_expr = ast.And(exprs=exprs)
    # This query only supports events at the moment.
    # TODO: Extend for other models that also wish to implement property filtering.
    select_query = ast.SelectQuery(
        select=[parse_expr("properties as properties")],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=and_expr,
    )
    prepared_select_query: ast.SelectQuery = typing.cast(
        ast.SelectQuery, prepare_ast_for_printing(select_query, context=context, dialect="hogql", stack=[select_query])
    )
    prepared_and_expr = prepare_ast_for_printing(
        and_expr, context=context, dialect="clickhouse", stack=[prepared_select_query]
    )

    printed = print_prepared_ast(
        prepared_and_expr,  # type: ignore
        context=context,
        dialect="clickhouse",
        stack=[prepared_select_query],
    )

    return printed, context.values


async def wait_for_delta_past_data_interval_end(
    data_interval_end: dt.datetime, delta: dt.timedelta = dt.timedelta(seconds=30)
) -> None:
    """Wait for some time after `data_interval_end` before querying ClickHouse."""
    if settings.TEST:
        return

    target = data_interval_end.astimezone(dt.UTC)
    now = dt.datetime.now(dt.UTC)

    while target + delta > now:
        now = dt.datetime.now(dt.UTC)
        remaining = (target + delta) - now
        # Sleep between 1-10 seconds, there shouldn't ever be the need to wait too long.
        await asyncio.sleep(min(max(remaining.total_seconds(), 1), 10))


class ConsumerFromStage:
    """Async consumer for batch exports.

    Attributes:
        data_interval_start: The beginning of the batch export period.
        logger: Provided consumer logger.
    """

    def __init__(
        self,
        data_interval_start: dt.datetime | str | None,
        data_interval_end: dt.datetime | str,
    ):
        self.data_interval_start = data_interval_start
        self.data_interval_end = data_interval_end
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
        file_format: str,
        compression: str | None,
        include_inserted_at: bool = False,
        max_file_size_bytes: int = 0,
        json_columns: collections.abc.Sequence[str] = ("properties", "person_properties", "set", "set_once"),
    ) -> int:
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
            Total number of records in all consumed record batches.
        """

        schema = cast_record_batch_schema_json_columns(schema, json_columns=json_columns)
        transformer = get_stream_transformer(
            format=file_format,
            compression=compression,
            schema=schema,
            include_inserted_at=include_inserted_at,
        )
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

                yield record_batch

        self.logger.info("Starting consumer from internal S3 stage")

        try:
            async for chunk, is_eof in transformer.iter(
                track_iteration_of_record_batches(),
                max_file_size_bytes,
            ):
                chunk_size = len(chunk)
                total_file_bytes_count += chunk_size

                self.logger.info(
                    f"Consuming transformed chunk. Record batch num rows: {num_records_in_batch:,}, "
                    f"record batch MiB: {num_bytes_in_batch / 1024**2:.2f}, "
                    f"data chunk MiB: {chunk_size / 1024**2:.2f}. "
                    f"Total records so far: {total_records_count:,}, "
                    f"total file MiB so far: {total_file_bytes_count / 1024**2:.2f}"
                )
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
        return total_records_count

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
    consumer: ConsumerFromStage,
    producer_task: asyncio.Task,
    schema: pa.Schema,
    file_format: str,
    compression: str | None,
    include_inserted_at: bool = False,
    max_file_size_bytes: int = 0,
    json_columns: collections.abc.Sequence[str] = ("properties", "person_properties", "set", "set_once"),
) -> int:
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
        Number of records exported. Not the number of record batches, but the number of records in all record batches.
    """
    records_completed = await consumer.start(
        queue=queue,
        producer_task=producer_task,
        schema=schema,
        file_format=file_format,
        compression=compression,
        include_inserted_at=include_inserted_at,
        max_file_size_bytes=max_file_size_bytes,
        json_columns=json_columns,
    )

    await raise_on_task_failure(producer_task)
    return records_completed
