import math
import time
import typing
import asyncio
import datetime as dt
import operator
import collections.abc

from django.conf import settings

import pyarrow as pa
from temporalio.common import MetricHistogram

from posthog.schema import EventPropertyFilter, HogQLPropertyFilter, HogQLQueryModifiers, MaterializationMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError
from posthog.hogql.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.visitor import TraversingVisitor

from posthog.models import Team
from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.service import SUPPORTED_FILTER_TYPES, BackfillDetails
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


class BatchExportField(typing.TypedDict):
    """A field to be queried from ClickHouse.

    Attributes:
        expression: A ClickHouse SQL expression that declares the field required.
        alias: An alias to apply to the expression (after an 'AS' keyword).
    """

    expression: str
    alias: str


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


class UpdatePropertiesToPersonProperties(TraversingVisitor):
    """Update 'properties' to 'events.poe.properties' in all fields."""

    def visit_field(self, node: ast.Field):
        if node.chain and node.chain[0] == "properties":
            node.chain = ["events", "poe", "properties", *node.chain[1:]]


class InvalidFilterError(Exception):
    """Error raised when an invalid filter is used."""

    def __init__(self, error: ExposedHogQLError | InternalHogQLError):
        if isinstance(error, ExposedHogQLError):
            msg = f"One or more provided filters are invalid: {error}"
        else:
            # TODO: Figure out if we can include some debug information from internal
            # errors too
            msg = "One or more provided filters are invalid"
        super().__init__(msg)


def compose_filters_clause(
    filters: list[dict[str, str | list[str] | None]],
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
        enable_select_queries=False,
        limit_top_select=False,
        within_non_hogql_query=False,
        # Export SQL reads the legacy String-properties tables/views (events, events_recent,
        # events_batch_export), so filter fragments must stay on the legacy schema. Remove this pin
        # only together with porting those views and field lists to events_json.
        use_new_events_schema=False,
        values=values or {},
        modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.DISABLED),
    )
    # Export models are only events/persons/sessions; warehouse tables and views are denied.
    # Pass bypass_warehouse_access_control=True or a user if that becomes an issue.
    context.database = Database.create_for(team=team, modifiers=context.modifiers)
    exprs = []
    for filter in filters:
        filter_type = filter["type"]
        if filter_type not in SUPPORTED_FILTER_TYPES:
            raise TypeError(f"Unknown filter type: '{filter_type}'")

        match filter_type:
            case "event":
                exprs.append(property_to_expr(EventPropertyFilter(**filter), team=team))
            case "person":
                # HACK: We are trying to apply the filter to 'events.person_properties' as that would
                # mimic workflows behavior of applying it to the person in the event but:
                # 1. PersonPropertyFilter expects a join with the person table, so we can't use it.
                # 2. 'persons_properties' doesn't exist in the HogQL 'EventsTable', so we can't use it.
                # So, we treat this filter like an events property filter (for 1) and manually update
                # the chain to point to 'events.poe.properties' which does exist in 'EventsTable' (for 2).
                # This will get resolved to 'events.person_properties' in ClickHouse dialect. This is done
                # using a visitor, which makes it slightly less of a hack.
                # I attempted to add a new property filter just for us to use here, but it was a mess
                # requiring multiple unnecessary (for us) file changes, and consistently failed type checks
                # everywhere in hogql modules.
                expr = property_to_expr(EventPropertyFilter(**{**filter, **{"type": "event"}}), team=team)
                UpdatePropertiesToPersonProperties().visit(expr)
                exprs.append(expr)

            case "hogql":
                try:
                    exprs.append(property_to_expr(HogQLPropertyFilter(**filter), team=team))
                except (ExposedHogQLError, InternalHogQLError) as e:
                    raise InvalidFilterError(e) from e

            case _:
                # Reachable only if SUPPORTED_FILTER_TYPES gains a type without a handler here.
                raise TypeError(f"Unhandled filter type: '{filter_type}'")

    and_expr = ast.And(exprs=exprs)
    # This query only supports events at the moment.
    # TODO: Extend for other models that also wish to implement property filtering.
    select_query = ast.SelectQuery(
        select=[
            parse_expr("properties as properties"),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=and_expr,
    )
    prepared_select_query: ast.SelectQuery = typing.cast(
        ast.SelectQuery, prepare_ast_for_printing(select_query, context=context, dialect="hogql", stack=[select_query])
    )
    prepared_and_expr = prepare_ast_for_printing(
        and_expr, context=context, dialect="clickhouse", stack=[prepared_select_query]
    )

    try:
        printed = print_prepared_ast(
            prepared_and_expr,  # type: ignore
            context=context,
            dialect="clickhouse",
            stack=[prepared_select_query],
        )
    except (ExposedHogQLError, InternalHogQLError) as e:
        raise InvalidFilterError(e) from e

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
