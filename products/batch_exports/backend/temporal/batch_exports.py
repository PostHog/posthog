import collections.abc
import dataclasses
import datetime as dt
import operator
import typing
import uuid

import pyarrow as pa
from django.conf import settings
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportBackfill, BatchExportRun
from posthog.batch_exports.service import (
    BackfillDetails,
    BatchExportField,
    acount_failed_batch_export_runs,
    apause_batch_export,
    cancel_running_batch_export_backfill,
    create_batch_export_backfill,
    create_batch_export_run,
    running_backfills_for_batch_export,
    update_batch_export_backfill_status,
    update_batch_export_run,
)
from posthog.settings.base_variables import TEST
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.common.client import connect
from posthog.temporal.common.logger import bind_contextvars, get_logger
from products.batch_exports.backend.temporal.metrics import (
    get_export_finished_metric,
    get_export_started_metric,
)
from products.batch_exports.backend.temporal.spmc import (
    use_distributed_events_recent_table,
)
from products.batch_exports.backend.temporal.sql import (
    SELECT_FROM_DISTRIBUTED_EVENTS_RECENT,
    SELECT_FROM_EVENTS_VIEW,
    SELECT_FROM_EVENTS_VIEW_BACKFILL,
    SELECT_FROM_EVENTS_VIEW_RECENT,
    SELECT_FROM_EVENTS_VIEW_UNBOUNDED,
)

LOGGER = get_logger()

BytesGenerator = collections.abc.Generator[bytes, None, None]
RecordsGenerator = collections.abc.Generator[pa.RecordBatch, None, None]

AsyncBytesGenerator = collections.abc.AsyncGenerator[bytes, None]
AsyncRecordsGenerator = collections.abc.AsyncGenerator[pa.RecordBatch, None]


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


class RecordBatchProducerError(Exception):
    """Raised when an error occurs during production of record batches."""

    def __init__(self):
        super().__init__("The record batch producer encountered an error during execution")


class TaskNotDoneError(Exception):
    """Raised when a task that should be done, isn't."""

    def __init__(self, task: str):
        super().__init__(f"Expected task '{task}' to be done by now")


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


def iter_records(
    client: ClickHouseClient,
    team_id: int,
    interval_start: str | None,
    interval_end: str,
    exclude_events: collections.abc.Iterable[str] | None = None,
    include_events: collections.abc.Iterable[str] | None = None,
    fields: list[BatchExportField] | None = None,
    filters_str: str | None = None,
    extra_query_parameters: dict[str, typing.Any] | None = None,
    is_backfill: bool = False,
    backfill_details: BackfillDetails | None = None,
) -> RecordsGenerator:
    """Iterate over Arrow batch records for a batch export.

    TODO: this can be removed once HTTP batch exports are migrated to SPMC

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
    if interval_start is not None:
        data_interval_start_ch = dt.datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    else:
        data_interval_start_ch = None

    data_interval_end_ch = dt.datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")

    if exclude_events:
        events_to_exclude_array = list(exclude_events)
    else:
        events_to_exclude_array = []

    if include_events:
        events_to_include_array = list(include_events)
    else:
        events_to_include_array = []

    if fields is None:
        query_fields = ",".join(f"{field['expression']} AS {field['alias']}" for field in default_fields())
    else:
        if "_inserted_at" not in [field["alias"] for field in fields]:
            control_fields = [BatchExportField(expression="_inserted_at", alias="_inserted_at")]
        else:
            control_fields = []

        query_fields = ",".join(f"{field['expression']} AS {field['alias']}" for field in fields + control_fields)

    base_query_parameters = {
        "team_id": team_id,
        "interval_start": data_interval_start_ch,
        "interval_end": data_interval_end_ch,
        "exclude_events": events_to_exclude_array,
        "include_events": events_to_include_array,
    }

    start_at = dt.datetime.fromisoformat(interval_start) if interval_start is not None else None
    end_at = dt.datetime.fromisoformat(interval_end)

    # TODO: this can be simplified once all backfill inputs are migrated
    is_backfill = (backfill_details is not None) or is_backfill

    if start_at:
        is_5_min_batch_export = (end_at - start_at) == dt.timedelta(seconds=300)
    else:
        is_5_min_batch_export = False

    # for 5 min batch exports we query the events_recent table, which is known to have zero replication lag, but
    # may not be able to handle the load from all batch exports
    if is_5_min_batch_export and not is_backfill:
        query = SELECT_FROM_EVENTS_VIEW_RECENT
    # for other batch exports that should use `events_recent` we use the `distributed_events_recent` table
    # which is a distributed table that sits in front of the `events_recent` table
    elif use_distributed_events_recent_table(
        is_backfill=is_backfill, backfill_details=backfill_details, data_interval_start=start_at
    ):
        query = SELECT_FROM_DISTRIBUTED_EVENTS_RECENT
    elif str(team_id) in settings.UNCONSTRAINED_TIMESTAMP_TEAM_IDS:
        query = SELECT_FROM_EVENTS_VIEW_UNBOUNDED
    elif is_backfill:
        query = SELECT_FROM_EVENTS_VIEW_BACKFILL
    else:
        query = SELECT_FROM_EVENTS_VIEW
        lookback_days = settings.OVERRIDE_TIMESTAMP_TEAM_IDS.get(team_id, settings.DEFAULT_TIMESTAMP_LOOKBACK_DAYS)
        base_query_parameters["lookback_days"] = lookback_days

    query_str = query.safe_substitute(
        fields=query_fields, filters=filters_str or "", order="ORDER BY _inserted_at, event"
    )

    if extra_query_parameters is not None:
        query_parameters = base_query_parameters | extra_query_parameters
    else:
        query_parameters = base_query_parameters

    yield from client.stream_query_as_arrow(query_str, query_parameters=query_parameters)


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
    data_interval_start: str | None
    data_interval_end: str
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None
    # this can be removed once all backfills are finished
    is_backfill: bool = False
    backfill_id: str | None = None


BatchExportRunId = str


@activity.defn
async def start_batch_export_run(inputs: StartBatchExportRunInputs) -> BatchExportRunId:
    """Activity that creates an BatchExportRun and returns the run id.

    Intended to be used in all export workflows, usually at the start, to create a model
    instance to represent them in our database.
    """
    bind_contextvars(
        team_id=inputs.team_id,
        batch_export_id=inputs.batch_export_id,
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        is_backfill=inputs.is_backfill,
        backfill_id=inputs.backfill_id,
    )
    logger = LOGGER.bind()
    logger.info(
        "Starting batch export for range %s - %s",
        inputs.data_interval_start,
        inputs.data_interval_end,
    )

    run = await database_sync_to_async(create_batch_export_run)(
        batch_export_id=uuid.UUID(inputs.batch_export_id),
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        status=BatchExportRun.Status.STARTING,
        backfill_id=uuid.UUID(inputs.backfill_id) if inputs.backfill_id else None,
    )

    return str(run.id)


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
    bind_contextvars(team_id=inputs.team_id, batch_export_id=inputs.batch_export_id, status=inputs.status)
    logger = LOGGER.bind()

    not_model_params = ("id", "team_id", "batch_export_id", "failure_threshold", "failure_check_window")
    update_params = {
        key: value
        for key, value in dataclasses.asdict(inputs).items()
        if key not in not_model_params and value is not None
    }

    latest_error = update_params.get("latest_error", None)
    if latest_error is not None and isinstance(latest_error, str):
        # NUL (\x00) bytes are not allowed in PostgreSQL, so we replace them in
        # the free text field `latest_error`.
        latest_error = latest_error.replace("\x00", "")
        update_params["latest_error"] = latest_error

    batch_export_run = await database_sync_to_async(update_batch_export_run)(
        run_id=uuid.UUID(inputs.id),
        finished_at=dt.datetime.now(dt.UTC),
        **update_params,
    )

    if batch_export_run.status == BatchExportRun.Status.FAILED_RETRYABLE:
        logger.error("Batch export failed with error: %s", batch_export_run.latest_error)

    elif batch_export_run.status == BatchExportRun.Status.FAILED:
        logger.error("Batch export failed with non-recoverable error: %s", batch_export_run.latest_error)

        from posthog.tasks.email import send_batch_export_run_failure

        try:
            await database_sync_to_async(send_batch_export_run_failure)(inputs.id)
        except Exception:
            logger.exception("Failure email notification could not be sent")
        else:
            logger.info("Failure notification email for run %s has been sent", inputs.id)

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
            logger.aexception("Ongoing backfills could not be automatically cancelled")
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
    start_at: str | None
    end_at: str | None
    status: str


@activity.defn
async def create_batch_export_backfill_model(inputs: CreateBatchExportBackfillInputs) -> str:
    """Activity that creates an BatchExportBackfill.

    Intended to be used in all batch export backfill workflows, usually at the start, to create a
    model instance to represent them in our database.
    """
    bind_contextvars(
        team_id=inputs.team_id,
        batch_export_id=inputs.batch_export_id,
        status=inputs.status,
        start_at=inputs.start_at,
        end_at=inputs.end_at,
    )
    logger = LOGGER.bind()

    logger.info(
        "Creating historical export for batches in range %s - %s",
        inputs.start_at,
        inputs.end_at,
    )
    backfill = await database_sync_to_async(create_batch_export_backfill)(
        batch_export_id=uuid.UUID(inputs.batch_export_id),
        start_at=inputs.start_at,
        end_at=inputs.end_at,
        status=inputs.status,
        team_id=inputs.team_id,
    )

    return str(backfill.id)


@dataclasses.dataclass
class UpdateBatchExportBackfillStatusInputs:
    """Inputs to the update_batch_export_backfill_status activity."""

    id: str
    status: str


@activity.defn
async def update_batch_export_backfill_model_status(inputs: UpdateBatchExportBackfillStatusInputs) -> None:
    """Activity that updates the status of an BatchExportBackfill."""
    bind_contextvars(
        id=inputs.id,
        status=inputs.status,
    )
    logger = LOGGER.bind()

    backfill = await database_sync_to_async(update_batch_export_backfill_status)(
        backfill_id=uuid.UUID(inputs.id),
        status=inputs.status,
        # we currently only call this once the backfill is finished, so we can set the finished_at here
        finished_at=dt.datetime.now(dt.UTC),
    )

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
    heartbeat_timeout_seconds: int | None = 180,
    maximum_attempts: int = 0,
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

    if TEST:
        maximum_attempts = 1

    if isinstance(settings.BATCH_EXPORT_HEARTBEAT_TIMEOUT_SECONDS, int):
        heartbeat_timeout_seconds = settings.BATCH_EXPORT_HEARTBEAT_TIMEOUT_SECONDS

    if interval == "hour":
        start_to_close_timeout = dt.timedelta(hours=6)
    elif interval == "day":
        start_to_close_timeout = dt.timedelta(days=1)
    elif interval.startswith("every"):
        _, value, unit = interval.split(" ")
        kwargs = {unit: int(value)}
        # TODO: Consider removing this 20 minute minimum once we are more confident about hitting 5 minute or lower SLAs.
        start_to_close_timeout = max(dt.timedelta(minutes=20), dt.timedelta(**kwargs))
    else:
        raise ValueError(f"Unsupported interval: '{interval}'")

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
