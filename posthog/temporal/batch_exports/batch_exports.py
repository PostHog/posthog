import asyncio
import collections.abc
import dataclasses
import datetime as dt
import typing
import uuid
from string import Template

import pyarrow as pa
from django.conf import settings
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportBackfill, BatchExportRun
from posthog.batch_exports.service import (
    BatchExportField,
    acount_failed_batch_export_runs,
    acreate_batch_export_backfill,
    acreate_batch_export_run,
    apause_batch_export,
    aupdate_batch_export_backfill_status,
    aupdate_batch_export_run,
    cancel_running_batch_export_backfill,
    running_backfills_for_batch_export,
)
from posthog.temporal.batch_exports.metrics import (
    get_export_finished_metric,
    get_export_started_metric,
)
from posthog.temporal.common.clickhouse import ClickHouseClient, get_client
from posthog.temporal.common.client import connect
from posthog.temporal.common.logger import bind_temporal_worker_logger

SELECT_QUERY_TEMPLATE = Template(
    """
    SELECT
    $distinct
    $fields
    FROM events
    WHERE
        team_id = {team_id}
        AND $timestamp_field >= toDateTime64({data_interval_start}, 6, 'UTC')
        AND $timestamp_field < toDateTime64({data_interval_end}, 6, 'UTC')
        $timestamp
        $exclude_events
        $include_events
    $order_by
    $format
    """
)

TIMESTAMP_PREDICATES = Template(
    """
-- These 'timestamp' checks are a heuristic to exploit the sort key.
-- Ideally, we need a schema that serves our needs, i.e. with a sort key on the _timestamp field used for batch exports.
-- As a side-effect, this heuristic will discard historical loads older than a day.
AND timestamp >= toDateTime64({data_interval_start}, 6, 'UTC') - INTERVAL $lookback_days DAY
AND timestamp < toDateTime64({data_interval_end}, 6, 'UTC') + INTERVAL 1 DAY
"""
)


def get_timestamp_predicates_for_team(team_id: int, is_backfill: bool = False) -> str:
    if str(team_id) in settings.UNCONSTRAINED_TIMESTAMP_TEAM_IDS or is_backfill:
        return ""
    else:
        return TIMESTAMP_PREDICATES.substitute(
            lookback_days=settings.OVERRIDE_TIMESTAMP_TEAM_IDS.get(team_id, settings.DEFAULT_TIMESTAMP_LOOKBACK_DAYS),
        )


def get_timestamp_field(is_backfill: bool) -> str:
    """Return the field to use for timestamp bounds."""
    if is_backfill:
        timestamp_field = "timestamp"
    else:
        timestamp_field = "COALESCE(inserted_at, _timestamp)"
    return timestamp_field


async def get_rows_count(
    client: ClickHouseClient,
    team_id: int,
    interval_start: str,
    interval_end: str,
    exclude_events: collections.abc.Iterable[str] | None = None,
    include_events: collections.abc.Iterable[str] | None = None,
    is_backfill: bool = False,
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

    timestamp_field = get_timestamp_field(is_backfill)
    timestamp_predicates = get_timestamp_predicates_for_team(team_id, is_backfill)

    query = SELECT_QUERY_TEMPLATE.substitute(
        fields="count(DISTINCT event, cityHash64(distinct_id), cityHash64(uuid)) as count",
        order_by="",
        format="",
        distinct="",
        timestamp_field=timestamp_field,
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
    is_backfill: bool = False,
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

    timestamp_field = get_timestamp_field(is_backfill)
    timestamp_predicates = get_timestamp_predicates_for_team(team_id, is_backfill)

    if fields is None:
        query_fields = ",".join(f"{field['expression']} AS {field['alias']}" for field in default_fields())
    else:
        if "_inserted_at" not in [field["alias"] for field in fields]:
            control_fields = [BatchExportField(expression="COALESCE(inserted_at, _timestamp)", alias="_inserted_at")]
        else:
            control_fields = []

        query_fields = ",".join(f"{field['expression']} AS {field['alias']}" for field in fields + control_fields)

    query = SELECT_QUERY_TEMPLATE.substitute(
        fields=query_fields,
        order_by="ORDER BY COALESCE(inserted_at, _timestamp)",
        format="FORMAT ArrowStream",
        distinct="DISTINCT ON (event, cityHash64(distinct_id), cityHash64(uuid))",
        timestamp_field=timestamp_field,
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

    yield from client.stream_query_as_arrow(query, query_parameters=query_parameters)


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
    is_backfill: bool = False


RecordsTotalCount = int | None
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

    delta = dt.datetime.fromisoformat(inputs.data_interval_end) - dt.datetime.fromisoformat(inputs.data_interval_start)
    async with get_client(team_id=inputs.team_id) as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        try:
            count = await asyncio.wait_for(
                get_rows_count(
                    client=client,
                    team_id=inputs.team_id,
                    interval_start=inputs.data_interval_start,
                    interval_end=inputs.data_interval_end,
                    exclude_events=inputs.exclude_events,
                    include_events=inputs.include_events,
                    is_backfill=inputs.is_backfill,
                ),
                timeout=(delta / 12).total_seconds(),
            )
        except asyncio.TimeoutError:
            count = None

    if count is None:
        logger.info(
            "Batch export for range %s - %s will continue without a count of rows to export",
            inputs.data_interval_start,
            inputs.data_interval_end,
        )
    elif count > 0:
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

    run = await acreate_batch_export_run(
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
        batch_export_id: The id of the batch export this run belongs to.
        team_id: The team id of the batch export.
        status: The status this batch export is finishing with.
        latest_error: The latest error message captured, if any.
        records_completed: Number of records successfully exported.
        records_total_count: Total count of records this run noted.
        failure_threshold: Used when determining to pause a batch export that has failed.
            See the docstring in 'pause_batch_export_if_over_failure_threshold'.
        failure_check_window: Used when determining to pause a batch export that has failed.
            See the docstring in 'pause_batch_export_if_over_failure_threshold'.
    """

    id: str
    batch_export_id: str
    team_id: int
    status: str
    latest_error: str | None = None
    records_completed: int | None = None
    records_total_count: int | None = None
    failure_threshold: int = 10
    failure_check_window: int = 50


@activity.defn
async def finish_batch_export_run(inputs: FinishBatchExportRunInputs) -> None:
    """Activity that finishes a 'BatchExportRun'.

    Finishing means setting and handling the status of a 'BatchExportRun' model, as well
    as setting any additional supported model attributes.

    The only status that requires handling is 'FAILED' as we also check if the number of failures in
    'failure_check_window' exceeds 'failure_threshold' and attempt to pause the batch export if
    that's the case. Also, a notification is sent to users on every failure.
    """
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    not_model_params = ("id", "team_id", "batch_export_id", "failure_threshold", "failure_check_window")
    update_params = {
        key: value
        for key, value in dataclasses.asdict(inputs).items()
        if key not in not_model_params and value is not None
    }
    batch_export_run = await aupdate_batch_export_run(
        run_id=uuid.UUID(inputs.id),
        finished_at=dt.datetime.now(),
        **update_params,
    )

    if batch_export_run.status == BatchExportRun.Status.FAILED_RETRYABLE:
        logger.error("Batch export failed with error: %s", batch_export_run.latest_error)

    elif batch_export_run.status == BatchExportRun.Status.FAILED:
        logger.error("Batch export failed with non-retryable error: %s", batch_export_run.latest_error)

        from posthog.tasks.email import send_batch_export_run_failure

        try:
            await send_batch_export_run_failure(inputs.id)
        except Exception:
            logger.exception("Failure email notification could not be sent")

        is_over_failure_threshold = await check_if_over_failure_threshold(
            inputs.batch_export_id,
            check_window=inputs.failure_check_window,
            failure_threshold=inputs.failure_threshold,
        )

        if not is_over_failure_threshold:
            return

        try:
            was_paused = await pause_batch_export_over_failure_threshold(inputs.batch_export_id)
        except Exception:
            # Pausing could error if the underlying schedule is deleted.
            # Our application logic should prevent that, but I want to log it in case it ever happens
            # as that would indicate a bug.
            logger.exception("Batch export could not be automatically paused")
        else:
            if was_paused:
                logger.warning(
                    "Batch export was automatically paused due to exceeding failure threshold and exhausting "
                    "all automated retries."
                    "The batch export can be unpaused after addressing any errors."
                )

        try:
            total_cancelled = await cancel_running_backfills(
                inputs.batch_export_id,
            )
        except Exception:
            logger.exception("Ongoing backfills could not be automatically cancelled")
        else:
            if total_cancelled > 0:
                logger.warning(
                    f"{total_cancelled} ongoing batch export backfill{'s' if total_cancelled > 1 else ''} "
                    f"{'were' if total_cancelled > 1 else 'was'} cancelled due to exceeding failure threshold "
                    " and exhausting all automated retries."
                    "The backfill can be triggered again after addressing any errors."
                )

    elif batch_export_run.status == BatchExportRun.Status.CANCELLED:
        logger.warning("Batch export was cancelled")

    else:
        logger.info(
            "Successfully finished exporting batch %s - %s",
            batch_export_run.data_interval_start,
            batch_export_run.data_interval_end,
        )


async def check_if_over_failure_threshold(batch_export_id: str, check_window: int, failure_threshold: int):
    """Check if a given batch export is over failure threshold.

    A 'check_window' was added to account for batch exports that have a history of failures but have some
    occassional successes in the middle. This is relevant particularly for low-volume exports:
    A batch export without rows to export always succeeds, even if it's not properly configured. So, the failures
    could be scattered between these successes.

    Keep in mind that if 'check_window' is less than 'failure_threshold', there is no point in even counting,
    so we raise an exception.

    Arguments:
        batch_export_id: The ID of the batch export to check and pause.
        check_window: The window of runs to consider for computing a count of failures.
        failure_threshold: The number of runs that must have failed for a batch export to be paused.

    Returns:
        A bool indicating if the batch export is paused.

    Raises:
        ValueError: If 'check_window' is smaller than 'failure_threshold' as that check would be redundant and,
            likely, a bug.
    """
    if check_window < failure_threshold:
        raise ValueError("'failure_threshold' cannot be higher than 'check_window'")

    count = await acount_failed_batch_export_runs(uuid.UUID(batch_export_id), last_n=check_window)

    if count < failure_threshold:
        return False
    return True


async def pause_batch_export_over_failure_threshold(batch_export_id: str) -> bool:
    """Pause a batch export once it exceeds failure threshold.

    Arguments:
        batch_export_id: The ID of the batch export to check and pause.

    Returns:
        A bool indicating if the batch export was paused or not.
    """
    client = await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_CLIENT_ROOT_CA,
        settings.TEMPORAL_CLIENT_CERT,
        settings.TEMPORAL_CLIENT_KEY,
    )

    was_paused = await apause_batch_export(
        client, batch_export_id=batch_export_id, note="Paused due to exceeding failure threshold"
    )

    return was_paused


async def cancel_running_backfills(batch_export_id: str) -> int:
    """Cancel any running batch export backfills.

    This is intended to be called once a batch export failure threshold has been exceeded.

    Arguments:
        batch_export_id: The ID of the batch export whose backfills will be cancelled.

    Returns:
        The number of cancelled backfills, if any.
    """
    client = await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_CLIENT_ROOT_CA,
        settings.TEMPORAL_CLIENT_CERT,
        settings.TEMPORAL_CLIENT_KEY,
    )

    total_cancelled = 0

    async for backfill in running_backfills_for_batch_export(uuid.UUID(batch_export_id)):
        await cancel_running_batch_export_backfill(client, backfill)

        total_cancelled += 1

    return total_cancelled


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
    run = await acreate_batch_export_backfill(
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
    backfill = await aupdate_batch_export_backfill_status(backfill_id=uuid.UUID(inputs.id), status=inputs.status)
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
    interval: str,
    heartbeat_timeout_seconds: int | None = 120,
    maximum_attempts: int = 15,
    initial_retry_interval_seconds: int = 30,
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
        interval: The interval of the batch export used to set the start to close timeout.
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

    if interval == "hour":
        start_to_close_timeout = dt.timedelta(hours=1)
    elif interval == "day":
        start_to_close_timeout = dt.timedelta(days=1)
    elif interval.startswith("every"):
        _, value, unit = interval.split(" ")
        kwargs = {unit: int(value)}
        # TODO: Consider removing this 10 minute minimum once we are more confident about hitting 5 minute or lower SLAs.
        start_to_close_timeout = max(dt.timedelta(minutes=10), dt.timedelta(**kwargs))
    else:
        raise ValueError(f"Unsupported interval: '{interval}'")

    try:
        records_completed = await workflow.execute_activity(
            activity,
            inputs,
            start_to_close_timeout=start_to_close_timeout,
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
