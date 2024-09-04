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
    BatchExportModel,
    BatchExportSchema,
    acount_failed_batch_export_runs,
    apause_batch_export,
    cancel_running_batch_export_backfill,
    create_batch_export_backfill,
    create_batch_export_run,
    running_backfills_for_batch_export,
    update_batch_export_backfill_status,
    update_batch_export_run,
)
from posthog.temporal.batch_exports.metrics import (
    get_export_finished_metric,
    get_export_started_metric,
)
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.common.client import connect
from posthog.temporal.common.logger import bind_temporal_worker_logger
from posthog.warehouse.util import database_sync_to_async

BytesGenerator = collections.abc.Generator[bytes, None, None]
RecordsGenerator = collections.abc.Generator[pa.RecordBatch, None, None]

AsyncBytesGenerator = collections.abc.AsyncGenerator[bytes, None]
AsyncRecordsGenerator = collections.abc.AsyncGenerator[pa.RecordBatch, None]

SELECT_FROM_PERSONS_VIEW = """
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons._inserted_at AS _inserted_at
FROM
    persons_batch_export(
        team_id={team_id},
        interval_start={interval_start},
        interval_end={interval_end}
    ) AS persons
FORMAT ArrowStream
-- This is half of configured MAX_MEMORY_USAGE for batch exports.
-- TODO: Make the setting available to all queries.
SETTINGS max_bytes_before_external_group_by=50000000000
"""

SELECT_FROM_EVENTS_VIEW = Template(
    """
SELECT
    $fields
FROM
    events_batch_export(
        team_id={team_id},
        lookback_days={lookback_days},
        interval_start={interval_start},
        interval_end={interval_end},
        include_events={include_events}::Array(String),
        exclude_events={exclude_events}::Array(String)
    ) AS events
FORMAT ArrowStream
"""
)

SELECT_FROM_EVENTS_VIEW_UNBOUNDED = Template(
    """
SELECT
    $fields
FROM
    events_batch_export_unbounded(
        team_id={team_id},
        interval_start={interval_start},
        interval_end={interval_end},
        include_events={include_events}::Array(String),
        exclude_events={exclude_events}::Array(String)
    ) AS events
FORMAT ArrowStream
"""
)

SELECT_FROM_EVENTS_VIEW_BACKFILL = Template(
    """
SELECT
    $fields
FROM
    events_batch_export_backfill(
        team_id={team_id},
        interval_start={interval_start},
        interval_end={interval_end},
        include_events={include_events}::Array(String),
        exclude_events={exclude_events}::Array(String)
    ) AS events
FORMAT ArrowStream
"""
)


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


async def iter_model_records(
    client: ClickHouseClient,
    model: BatchExportModel | BatchExportSchema | None,
    team_id: int,
    is_backfill: bool,
    destination_default_fields: list[BatchExportField] | None = None,
    **parameters,
) -> AsyncRecordsGenerator:
    if destination_default_fields is None:
        batch_export_default_fields = default_fields()
    else:
        batch_export_default_fields = destination_default_fields

    if isinstance(model, BatchExportModel):
        async for record in iter_records_from_model_view(
            client=client,
            model_name=model.name,
            team_id=team_id,
            is_backfill=is_backfill,
            fields=model.schema["fields"] if model.schema is not None else batch_export_default_fields,
            extra_query_parameters=model.schema["values"] if model.schema is not None else None,
            **parameters,
        ):
            yield record

    else:
        for record in iter_records(
            client,
            team_id=team_id,
            is_backfill=is_backfill,
            fields=model["fields"] if model is not None else batch_export_default_fields,
            extra_query_parameters=model["values"] if model is not None else None,
            **parameters,
        ):
            yield record


async def iter_records_from_model_view(
    client: ClickHouseClient,
    model_name: str,
    is_backfill: bool,
    team_id: int,
    interval_start: str,
    interval_end: str,
    fields: list[BatchExportField],
    **parameters,
) -> AsyncRecordsGenerator:
    if model_name == "persons":
        view = SELECT_FROM_PERSONS_VIEW
    else:
        if parameters["exclude_events"]:
            parameters["exclude_events"] = list(parameters["exclude_events"])
        else:
            parameters["exclude_events"] = []

        if parameters["include_events"]:
            parameters["include_events"] = list(parameters["include_events"])
        else:
            parameters["include_events"] = []

        if str(team_id) in settings.UNCONSTRAINED_TIMESTAMP_TEAM_IDS:
            query_template = SELECT_FROM_EVENTS_VIEW_UNBOUNDED
        elif is_backfill:
            query_template = SELECT_FROM_EVENTS_VIEW_BACKFILL
        else:
            query_template = SELECT_FROM_EVENTS_VIEW
            lookback_days = settings.OVERRIDE_TIMESTAMP_TEAM_IDS.get(team_id, settings.DEFAULT_TIMESTAMP_LOOKBACK_DAYS)
            parameters["lookback_days"] = lookback_days

        if "_inserted_at" not in [field["alias"] for field in fields]:
            control_fields = [BatchExportField(expression="_inserted_at", alias="_inserted_at")]
        else:
            control_fields = []

        query_fields = ",".join(f"{field['expression']} AS {field['alias']}" for field in fields + control_fields)

        view = query_template.substitute(fields=query_fields)

    parameters["team_id"] = team_id
    parameters["interval_start"] = dt.datetime.fromisoformat(interval_start).strftime("%Y-%m-%d %H:%M:%S")
    parameters["interval_end"] = dt.datetime.fromisoformat(interval_end).strftime("%Y-%m-%d %H:%M:%S")
    extra_query_parameters = parameters.pop("extra_query_parameters") or {}
    parameters = {**parameters, **extra_query_parameters}

    async for record_batch in client.astream_query_as_arrow(
        query=view,
        query_parameters=parameters,
    ):
        yield record_batch


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
    if str(team_id) in settings.UNCONSTRAINED_TIMESTAMP_TEAM_IDS:
        query = SELECT_FROM_EVENTS_VIEW_UNBOUNDED
    elif is_backfill:
        query = SELECT_FROM_EVENTS_VIEW_BACKFILL
    else:
        query = SELECT_FROM_EVENTS_VIEW
        lookback_days = settings.OVERRIDE_TIMESTAMP_TEAM_IDS.get(team_id, settings.DEFAULT_TIMESTAMP_LOOKBACK_DAYS)
        base_query_parameters["lookback_days"] = lookback_days

    query_str = query.substitute(fields=query_fields)

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
    data_interval_start: str
    data_interval_end: str
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None
    is_backfill: bool = False


BatchExportRunId = str


@activity.defn
async def start_batch_export_run(inputs: StartBatchExportRunInputs) -> BatchExportRunId:
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

    run = await database_sync_to_async(create_batch_export_run)(
        batch_export_id=uuid.UUID(inputs.batch_export_id),
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        status=BatchExportRun.Status.STARTING,
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
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    not_model_params = ("id", "team_id", "batch_export_id", "failure_threshold", "failure_check_window")
    update_params = {
        key: value
        for key, value in dataclasses.asdict(inputs).items()
        if key not in not_model_params and value is not None
    }
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
    run = await database_sync_to_async(create_batch_export_backfill)(
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
    backfill = await database_sync_to_async(update_batch_export_backfill_status)(
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

    if interval == "hour":
        start_to_close_timeout = dt.timedelta(hours=1)
    elif interval == "day":
        start_to_close_timeout = dt.timedelta(days=1)
        maximum_attempts = 0
    elif interval.startswith("every"):
        _, value, unit = interval.split(" ")
        kwargs = {unit: int(value)}
        # TODO: Consider removing this 10 minute minimum once we are more confident about hitting 5 minute or lower SLAs.
        start_to_close_timeout = max(dt.timedelta(minutes=10), dt.timedelta(**kwargs))
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
