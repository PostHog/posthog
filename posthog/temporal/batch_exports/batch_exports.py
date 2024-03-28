import collections.abc
import dataclasses
import datetime as dt
import typing
import uuid
from string import Template

import pyarrow as pa
from asgiref.sync import sync_to_async
from django.conf import settings
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportBackfill, BatchExportRun
from posthog.batch_exports.service import (
    BatchExportField,
    create_batch_export_backfill,
    create_batch_export_run,
    update_batch_export_backfill_status,
    update_batch_export_run,
)
from posthog.temporal.batch_exports.metrics import (
    get_export_finished_metric,
    get_export_started_metric,
)
from posthog.temporal.common.clickhouse import ClickHouseClient, get_client
from posthog.temporal.common.logger import bind_temporal_worker_logger

SELECT_QUERY_TEMPLATE = Template(
    """
    SELECT
    $distinct
    $fields
    FROM events
    WHERE
        COALESCE(inserted_at, _timestamp) >= toDateTime64({data_interval_start}, 6, 'UTC')
        AND COALESCE(inserted_at, _timestamp) < toDateTime64({data_interval_end}, 6, 'UTC')
        AND team_id = {team_id}
        $timestamp
        $exclude_events
        $include_events
    $order_by
    $format
    """
)

TIMESTAMP_PREDICATES = """
-- These 'timestamp' checks are a heuristic to exploit the sort key.
-- Ideally, we need a schema that serves our needs, i.e. with a sort key on the _timestamp field used for batch exports.
-- As a side-effect, this heuristic will discard historical loads older than a day.
AND timestamp >= toDateTime64({data_interval_start}, 6, 'UTC') - INTERVAL 2 DAY
AND timestamp < toDateTime64({data_interval_end}, 6, 'UTC') + INTERVAL 1 DAY
"""


async def get_rows_count(
    client: ClickHouseClient,
    team_id: int,
    interval_start: str,
    interval_end: str,
    exclude_events: collections.abc.Iterable[str] | None = None,
    include_events: collections.abc.Iterable[str] | None = None,
) -> int:
    """Return a count of rows to be batch exported."""
    data_interval_start_ch = dt.datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = dt.datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")

    if exclude_events:
        exclude_events_statement = "AND event NOT IN {exclude_events}"
        events_to_exclude_tuple = tuple(exclude_events)
    else:
        exclude_events_statement = ""
        events_to_exclude_tuple = ()

    if include_events:
        include_events_statement = "AND event IN {include_events}"
        events_to_include_tuple = tuple(include_events)
    else:
        include_events_statement = ""
        events_to_include_tuple = ()

    timestamp_predicates = TIMESTAMP_PREDICATES
    if str(team_id) in settings.UNCONSTRAINED_TIMESTAMP_TEAM_IDS:
        timestamp_predicates = ""

    query = SELECT_QUERY_TEMPLATE.substitute(
        fields="count(DISTINCT event, cityHash64(distinct_id), cityHash64(uuid)) as count",
        order_by="",
        format="",
        distinct="",
        timestamp=timestamp_predicates,
        exclude_events=exclude_events_statement,
        include_events=include_events_statement,
    )

    count = await client.read_query(
        query,
        query_parameters={
            "team_id": team_id,
            "data_interval_start": data_interval_start_ch,
            "data_interval_end": data_interval_end_ch,
            "exclude_events": events_to_exclude_tuple,
            "include_events": events_to_include_tuple,
        },
    )

    if count is None or len(count) == 0:
        raise ValueError("Unexpected result from ClickHouse: `None` returned for count query")

    return int(count)


def default_fields() -> list[BatchExportField]:
    """Return list of default batch export Fields."""
    return [
        BatchExportField(expression="toString(uuid)", alias="uuid"),
        BatchExportField(expression="team_id", alias="team_id"),
        BatchExportField(expression="timestamp", alias="timestamp"),
        BatchExportField(expression="COALESCE(inserted_at, _timestamp)", alias="_inserted_at"),
        BatchExportField(expression="created_at", alias="created_at"),
        BatchExportField(expression="event", alias="event"),
        BatchExportField(expression="nullIf(properties, '')", alias="properties"),
        BatchExportField(expression="toString(distinct_id)", alias="distinct_id"),
        BatchExportField(expression="nullIf(JSONExtractString(properties, '$set'), '')", alias="set"),
        BatchExportField(
            expression="nullIf(JSONExtractString(properties, '$set_once'), '')",
            alias="set_once",
        ),
    ]


BytesGenerator = collections.abc.Generator[bytes, None, None]
RecordsGenerator = collections.abc.Generator[pa.RecordBatch, None, None]

# Spoiler: We'll use these ones later 8)
# AsyncBytesGenerator = collections.abc.AsyncGenerator[bytes, None]
# AsyncRecordsGenerator = collections.abc.AsyncGenerator[pa.RecordBatch, None]


def iter_records(
    client: ClickHouseClient,
    team_id: int,
    interval_start: str,
    interval_end: str,
    exclude_events: collections.abc.Iterable[str] | None = None,
    include_events: collections.abc.Iterable[str] | None = None,
    fields: list[BatchExportField] | None = None,
    extra_query_parameters: dict[str, typing.Any] | None = None,
) -> RecordsGenerator:
    """Iterate over Arrow batch records for a batch export.

    Args:
        client: The ClickHouse client used to query for the batch records.
        team_id: The ID of the team whose data we are querying.
        interval_start: The beginning of the batch export interval.
        interval_end: The end of the batch export interval.
        exclude_events: Optionally, any event names that should be excluded.
        include_events: Optionally, the event names that should only be included in the export.
        fields: The fields that will be queried from ClickHouse. Will call default_fields if not set.
        extra_query_parameters: A dictionary of additional query parameters to pass to the query execution.
            Useful if fields contains any fields with placeholders.

    Returns:
        A generator that yields tuples of batch records as Python dictionaries and their schema.
    """
    data_interval_start_ch = dt.datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = dt.datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")

    if exclude_events:
        exclude_events_statement = "AND event NOT IN {exclude_events}"
        events_to_exclude_tuple = tuple(exclude_events)
    else:
        exclude_events_statement = ""
        events_to_exclude_tuple = ()

    if include_events:
        include_events_statement = "AND event IN {include_events}"
        events_to_include_tuple = tuple(include_events)
    else:
        include_events_statement = ""
        events_to_include_tuple = ()

    timestamp_predicates = TIMESTAMP_PREDICATES
    if str(team_id) in settings.UNCONSTRAINED_TIMESTAMP_TEAM_IDS:
        timestamp_predicates = ""

    if fields is None:
        query_fields = ",".join((f"{field['expression']} AS {field['alias']}" for field in default_fields()))
    else:
        if "_inserted_at" not in [field["alias"] for field in fields]:
            control_fields = [BatchExportField(expression="COALESCE(inserted_at, _timestamp)", alias="_inserted_at")]
        else:
            control_fields = []

        query_fields = ",".join((f"{field['expression']} AS {field['alias']}" for field in fields + control_fields))

    query = SELECT_QUERY_TEMPLATE.substitute(
        fields=query_fields,
        order_by="ORDER BY COALESCE(inserted_at, _timestamp)",
        format="FORMAT ArrowStream",
        distinct="DISTINCT ON (event, cityHash64(distinct_id), cityHash64(uuid))",
        timestamp=timestamp_predicates,
        exclude_events=exclude_events_statement,
        include_events=include_events_statement,
    )
    base_query_parameters = {
        "team_id": team_id,
        "data_interval_start": data_interval_start_ch,
        "data_interval_end": data_interval_end_ch,
        "exclude_events": events_to_exclude_tuple,
        "include_events": events_to_include_tuple,
    }

    if extra_query_parameters is not None:
        query_parameters = base_query_parameters | extra_query_parameters
    else:
        query_parameters = base_query_parameters

    for record_batch in client.stream_query_as_arrow(query, query_parameters=query_parameters):
        yield record_batch


def get_data_interval(interval: str, data_interval_end: str | None) -> tuple[dt.datetime, dt.datetime]:
    """Return the start and end of an export's data interval.

    Args:
        interval: The interval of the BatchExport associated with this Workflow.
        data_interval_end: The optional end of the BatchExport period. If not included, we will
            attempt to extract it from Temporal SearchAttributes.

    Raises:
        TypeError: If when trying to obtain the data interval end we run into non-str types.
        ValueError: If passing an unsupported interval value.

    Returns:
        A tuple of two dt.datetime indicating start and end of the data_interval.
    """
    data_interval_end_str = data_interval_end

    if not data_interval_end_str:
        data_interval_end_search_attr = workflow.info().search_attributes.get("TemporalScheduledStartTime")

        # These two if-checks are a bit pedantic, but Temporal SDK is heavily typed.
        # So, they exist to make mypy happy.
        if data_interval_end_search_attr is None:
            msg = (
                "Expected 'TemporalScheduledStartTime' of type 'list[str]' or 'list[datetime], found 'NoneType'."
                "This should be set by the Temporal Schedule unless triggering workflow manually."
                "In the latter case, ensure '{Type}BatchExportInputs.data_interval_end' is set."
            )
            raise TypeError(msg)

        # Failing here would perhaps be a bug in Temporal.
        if isinstance(data_interval_end_search_attr[0], str):
            data_interval_end_str = data_interval_end_search_attr[0]
            data_interval_end_dt = dt.datetime.fromisoformat(data_interval_end_str)

        elif isinstance(data_interval_end_search_attr[0], dt.datetime):
            data_interval_end_dt = data_interval_end_search_attr[0]

        else:
            msg = (
                f"Expected search attribute to be of type 'str' or 'datetime' but found '{data_interval_end_search_attr[0]}' "
                f"of type '{type(data_interval_end_search_attr[0])}'."
            )
            raise TypeError(msg)
    else:
        data_interval_end_dt = dt.datetime.fromisoformat(data_interval_end_str)

    if interval == "hour":
        data_interval_start_dt = data_interval_end_dt - dt.timedelta(hours=1)
    elif interval == "day":
        data_interval_start_dt = data_interval_end_dt - dt.timedelta(days=1)
    elif interval.startswith("every"):
        _, value, unit = interval.split(" ")
        kwargs = {unit: int(value)}
        data_interval_start_dt = data_interval_end_dt - dt.timedelta(**kwargs)
    else:
        raise ValueError(f"Unsupported interval: '{interval}'")

    return (data_interval_start_dt, data_interval_end_dt)


@dataclasses.dataclass
class StartBatchExportRunInputs:
    """Inputs to the 'start_batch_export_run' activity.

    Attributes:
        team_id: The id of the team the BatchExportRun belongs to.
        batch_export_id: The id of the BatchExport this BatchExportRun belongs to.
        data_interval_start: Start of this BatchExportRun's data interval.
        data_interval_end: End of this BatchExportRun's data interval.
        exclude_events: Optionally, any event names that should be excluded.
        include_events: Optionally, the event names that should only be included in the export.
    """

    team_id: int
    batch_export_id: str
    data_interval_start: str
    data_interval_end: str
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None


RecordsTotalCount = int
BatchExportRunId = str


@activity.defn
async def start_batch_export_run(inputs: StartBatchExportRunInputs) -> tuple[BatchExportRunId, RecordsTotalCount]:
    """Activity that creates an BatchExportRun and returns the count of records to export.

    Intended to be used in all export workflows, usually at the start, to create a model
    instance to represent them in our database.

    Upon seeing a count of 0 records to export, batch export workflows should finish early
    (i.e. without running the insert activity), as there will be nothing to export.
    """
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)
    logger.info(
        "Starting batch export for range %s - %s",
        inputs.data_interval_start,
        inputs.data_interval_end,
    )

    async with get_client(team_id=inputs.team_id) as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        count = await get_rows_count(
            client=client,
            team_id=inputs.team_id,
            interval_start=inputs.data_interval_start,
            interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
        )

    if count > 0:
        logger.info(
            "Batch export for range %s - %s will export %s rows",
            inputs.data_interval_start,
            inputs.data_interval_end,
            count,
        )
    else:
        logger.info(
            "Batch export for range %s - %s has no rows to export",
            inputs.data_interval_start,
            inputs.data_interval_end,
        )

    # 'sync_to_async' type hints are fixed in asgiref>=3.4.1
    # But one of our dependencies is pinned to asgiref==3.3.2.
    # Remove these comments once we upgrade.
    run = await sync_to_async(create_batch_export_run)(
        batch_export_id=uuid.UUID(inputs.batch_export_id),
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        status=BatchExportRun.Status.STARTING,
        records_total_count=count,
    )

    return str(run.id), count


@dataclasses.dataclass
class FinishBatchExportRunInputs:
    """Inputs to the 'finish_batch_export_run' activity.

    Attributes:
        id: The id of the batch export run. This should be a valid UUID string.
        team_id: The team id of the batch export.
        status: The status this batch export is finishing with.
        latest_error: The latest error message captured, if any.
        records_completed: Number of records successfully exported.
        records_total_count: Total count of records this run noted.
    """

    id: str
    team_id: int
    status: str
    latest_error: str | None = None
    records_completed: int | None = None
    records_total_count: int | None = None


@activity.defn
async def finish_batch_export_run(inputs: FinishBatchExportRunInputs) -> None:
    """Activity that finishes a BatchExportRun.

    Finishing means a final update to the status of the BatchExportRun model.
    """
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    update_params = {
        key: value
        for key, value in dataclasses.asdict(inputs).items()
        if key not in ("id", "team_id") and value is not None
    }
    batch_export_run = await sync_to_async(update_batch_export_run)(
        run_id=uuid.UUID(inputs.id),
        finished_at=dt.datetime.now(),
        **update_params,
    )

    if batch_export_run.status in (BatchExportRun.Status.FAILED, BatchExportRun.Status.FAILED_RETRYABLE):
        logger.error("BatchExport failed with error: %s", batch_export_run.latest_error)

    elif batch_export_run.status == BatchExportRun.Status.CANCELLED:
        logger.warning("BatchExport was cancelled.")

    else:
        logger.info(
            "Successfully finished exporting batch %s - %s",
            batch_export_run.data_interval_start,
            batch_export_run.data_interval_end,
        )


@dataclasses.dataclass
class CreateBatchExportBackfillInputs:
    team_id: int
    batch_export_id: str
    start_at: str
    end_at: str | None
    status: str


@activity.defn
async def create_batch_export_backfill_model(inputs: CreateBatchExportBackfillInputs) -> str:
    """Activity that creates an BatchExportBackfill.

    Intended to be used in all batch export backfill workflows, usually at the start, to create a
    model instance to represent them in our database.
    """
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)
    logger.info(
        "Creating historical export for batches in range %s - %s",
        inputs.start_at,
        inputs.end_at,
    )
    # 'sync_to_async' type hints are fixed in asgiref>=3.4.1
    # But one of our dependencies is pinned to asgiref==3.3.2.
    # Remove these comments once we upgrade.
    run = await sync_to_async(create_batch_export_backfill)(
        batch_export_id=uuid.UUID(inputs.batch_export_id),
        start_at=inputs.start_at,
        end_at=inputs.end_at,
        status=inputs.status,
        team_id=inputs.team_id,
    )

    return str(run.id)


@dataclasses.dataclass
class UpdateBatchExportBackfillStatusInputs:
    """Inputs to the update_batch_export_backfill_status activity."""

    id: str
    status: str


@activity.defn
async def update_batch_export_backfill_model_status(inputs: UpdateBatchExportBackfillStatusInputs) -> None:
    """Activity that updates the status of an BatchExportRun."""
    backfill = await sync_to_async(update_batch_export_backfill_status)(
        backfill_id=uuid.UUID(inputs.id), status=inputs.status
    )
    logger = await bind_temporal_worker_logger(team_id=backfill.team_id)

    if backfill.status in (BatchExportBackfill.Status.FAILED, BatchExportBackfill.Status.FAILED_RETRYABLE):
        logger.error("Historical export failed")

    elif backfill.status == BatchExportBackfill.Status.CANCELLED:
        logger.warning("Historical export was cancelled.")

    else:
        logger.info(
            "Successfully finished exporting historical batches in %s - %s",
            backfill.start_at,
            backfill.end_at,
        )


RecordsCompleted = int
BatchExportActivity = collections.abc.Callable[..., collections.abc.Awaitable[RecordsCompleted]]


async def execute_batch_export_insert_activity(
    activity: BatchExportActivity,
    inputs,
    non_retryable_error_types: list[str],
    finish_inputs: FinishBatchExportRunInputs,
    start_to_close_timeout_seconds: int = 3600,
    heartbeat_timeout_seconds: int | None = 120,
    maximum_attempts: int = 10,
    initial_retry_interval_seconds: int = 10,
    maximum_retry_interval_seconds: int = 120,
) -> None:
    """Execute the main insert activity of a batch export handling any errors.

    All batch exports boil down to inserting some data somewhere, and they all follow the same error
    handling patterns: logging and updating run status. For this reason, we have this function
    to abstract executing the main insert activity of each batch export.

    Args:
        activity: The 'insert_into_*' activity function to execute.
        inputs: The inputs to the activity.
        non_retryable_error_types: A list of errors to not retry on when executing the activity.
        finish_inputs: Inputs to the 'finish_batch_export_run' to run at the end.
        start_to_close_timeout: A timeout for the 'insert_into_*' activity function.
        maximum_attempts: Maximum number of retries for the 'insert_into_*' activity function.
            Assuming the error that triggered the retry is not in non_retryable_error_types.
        initial_retry_interval_seconds: When retrying, seconds until the first retry.
        maximum_retry_interval_seconds: Maximum interval in seconds between retries.
    """
    get_export_started_metric().add(1)
    retry_policy = RetryPolicy(
        initial_interval=dt.timedelta(seconds=initial_retry_interval_seconds),
        maximum_interval=dt.timedelta(seconds=maximum_retry_interval_seconds),
        maximum_attempts=maximum_attempts,
        non_retryable_error_types=non_retryable_error_types,
    )

    try:
        records_completed = await workflow.execute_activity(
            activity,
            inputs,
            start_to_close_timeout=dt.timedelta(seconds=start_to_close_timeout_seconds),
            heartbeat_timeout=dt.timedelta(seconds=heartbeat_timeout_seconds) if heartbeat_timeout_seconds else None,
            retry_policy=retry_policy,
        )
        finish_inputs.records_completed = records_completed

    except exceptions.ActivityError as e:
        if isinstance(e.cause, exceptions.CancelledError):
            finish_inputs.status = BatchExportRun.Status.CANCELLED
        elif isinstance(e.cause, exceptions.ApplicationError) and e.cause.type not in non_retryable_error_types:
            finish_inputs.status = BatchExportRun.Status.FAILED_RETRYABLE
        else:
            finish_inputs.status = BatchExportRun.Status.FAILED

        finish_inputs.latest_error = str(e.cause)
        raise

    except Exception:
        finish_inputs.status = BatchExportRun.Status.FAILED
        finish_inputs.latest_error = "An unexpected error has ocurred"
        raise

    finally:
        get_export_finished_metric(status=finish_inputs.status.lower()).add(1)

        await workflow.execute_activity(
            finish_batch_export_run,
            finish_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )
