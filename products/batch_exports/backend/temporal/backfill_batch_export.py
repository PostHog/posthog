import json
import typing
import asyncio
import datetime as dt
import dataclasses
import collections.abc

from django.conf import settings

import temporalio
import temporalio.client
import temporalio.common
import temporalio.activity
import temporalio.workflow
import temporalio.exceptions
from asgiref.sync import sync_to_async
from structlog.contextvars import bind_contextvars

from posthog.batch_exports.models import BatchExport, BatchExportBackfill
from posthog.batch_exports.service import BackfillBatchExportInputs, BackfillDetails, unpause_batch_export
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.client import connect
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import (
    CreateBatchExportBackfillInputs,
    UpdateBatchExportBackfillInputs,
    create_batch_export_backfill_model,
    update_batch_export_backfill_activity,
)
from products.batch_exports.backend.temporal.spmc import compose_filters_clause

LOGGER = get_write_only_logger(__name__)


class TemporalScheduleNotFoundError(Exception):
    """Exception raised when a Temporal Schedule is not found."""

    def __init__(self, schedule_id: str):
        super().__init__(f"The Temporal Schedule {schedule_id} was not found (maybe it was deleted?)")


class HeartbeatDetails(typing.NamedTuple):
    """Details sent over in a Temporal Activity heartbeat."""

    schedule_id: str
    workflow_id: str
    last_batch_data_interval_end: str


@dataclasses.dataclass
class GetBackfillInfoInputs:
    """Inputs for the get_backfill_info Activity."""

    team_id: int
    batch_export_id: str
    start_at: str | None
    end_at: str | None


@dataclasses.dataclass
class GetBackfillInfoOutputs:
    """Outputs from the get_backfill_info Activity."""

    adjusted_start_at: str | None
    total_records_count: int | None
    interval_seconds: float


def _align_timestamp_to_interval(timestamp: dt.datetime, batch_export: BatchExport) -> dt.datetime:
    """Align a timestamp to the batch export's interval boundary.

    For batch exports, intervals can have an offset from the default start time,
    specified in the batch export's timezone. For example, a daily export might
    run at 5am US/Pacific instead of midnight UTC.

    Args:
        timestamp: The timestamp to align (must be timezone-aware, typically UTC).
        batch_export: The batch export configuration with interval, offset, and timezone.

    Returns:
        The start of the interval containing the timestamp (in UTC).

    Examples:
        Daily interval at 5am UTC:
        - 2021-01-15 10:30:00 UTC aligns to 2021-01-15 05:00:00 UTC
        - 2021-01-15 04:30:00 UTC aligns to 2021-01-14 05:00:00 UTC

        Daily interval at 1am US/Pacific (PST = UTC-8 in winter):
        - 2021-01-15 10:00:00 UTC (= 02:00 PST) aligns to 2021-01-15 09:00:00 UTC (= 01:00 PST)
        - 2021-01-15 08:30:00 UTC (= 00:30 PST) aligns to 2021-01-14 09:00:00 UTC (= 01:00 PST prev day)
    """
    interval = batch_export.interval
    interval_seconds = int(batch_export.interval_time_delta.total_seconds())

    # For hourly or sub-hourly intervals, timezone doesn't matter
    if interval == "hour" or interval.startswith("every"):
        ts = timestamp.timestamp()
        aligned = (ts // interval_seconds) * interval_seconds
        return dt.datetime.fromtimestamp(aligned, tz=dt.UTC)

    # Convert timestamp to the batch export's timezone for alignment
    tz = batch_export.timezone_info
    local_timestamp = timestamp.astimezone(tz)
    offset_hour = batch_export.offset_hour or 0

    if interval == "day":
        # Find the start of the current "day" (which starts at offset_hour in local time)
        day_start = local_timestamp.replace(hour=offset_hour, minute=0, second=0, microsecond=0)
        if day_start > local_timestamp:
            day_start -= dt.timedelta(days=1)
        return day_start.astimezone(dt.UTC)

    elif interval == "week":
        offset_day = batch_export.offset_day or 0

        # Get current day of week (Monday=0, Sunday=6 in Python)
        # But batch exports use Sunday=0, so we need to convert
        python_weekday = local_timestamp.weekday()  # Monday=0
        batch_export_weekday = (python_weekday + 1) % 7  # Sunday=0

        # Calculate days since the start of the week (at offset_day)
        days_since_week_start = (batch_export_weekday - offset_day) % 7

        # Find the start of the current "week"
        week_start_date = local_timestamp.date() - dt.timedelta(days=days_since_week_start)
        week_start = dt.datetime.combine(
            week_start_date,
            dt.time(hour=offset_hour, minute=0, second=0),
            tzinfo=tz,
        )

        if week_start > local_timestamp:
            week_start -= dt.timedelta(weeks=1)

        return week_start.astimezone(dt.UTC)

    else:
        raise ValueError(f"Unknown interval: {interval}")


async def _get_backfill_info_for_events(
    batch_export: BatchExport,
    start_at: dt.datetime | None,
    end_at: dt.datetime | None,
    include_events: list[str],
    exclude_events: list[str],
    filters_str: str,
    extra_query_parameters: dict[str, typing.Any],
) -> tuple[dt.datetime | None, int]:
    """Get adjusted start time and estimated record count for events model.

    Returns:
        A tuple of (adjusted_start_at, estimated_records_count).
        If no data exists, returns (None, 0).
    """
    team_id = batch_export.team_id

    date_conditions = ""
    if start_at is not None:
        date_conditions += "AND timestamp >= %(start_at)s "
        # Convert to UTC to avoid ClickHouse timezone parsing issues (e.g., UTC+05:45)
        extra_query_parameters["start_at"] = start_at.astimezone(dt.UTC)
    if end_at is not None:
        date_conditions += "AND timestamp < %(end_at)s "
        extra_query_parameters["end_at"] = end_at.astimezone(dt.UTC)

    query = f"""
        SELECT
            MIN(timestamp) as min_timestamp,
            count() as record_count
        FROM events
        WHERE team_id = %(team_id)s
        AND timestamp > '2000-01-01'
        AND (length(%(include_events)s) = 0 OR event IN %(include_events)s)
        AND (length(%(exclude_events)s) = 0 OR event NOT IN %(exclude_events)s)
        {filters_str}
        {date_conditions}
        FORMAT JSONEachRow
    """

    query_parameters = {
        "team_id": team_id,
        "include_events": include_events,
        "exclude_events": exclude_events,
        **extra_query_parameters,
    }

    async with get_client(team_id=team_id) as client:
        result = await client.read_query_as_jsonl(query, query_parameters=query_parameters)

    min_timestamp_str = result[0]["min_timestamp"]
    record_count = int(result[0]["record_count"])

    # ClickHouse returns 1970-01-01 00:00:00 when there's no data
    # Make timezone-aware (UTC) for comparison with input datetimes
    min_timestamp = dt.datetime.fromisoformat(min_timestamp_str)
    if min_timestamp.tzinfo is None:
        min_timestamp = min_timestamp.replace(tzinfo=dt.UTC)
    else:
        min_timestamp = min_timestamp.astimezone(dt.UTC)

    if min_timestamp.year == 1970:
        return None, 0

    # Align to interval boundary considering the batch export's offset and timezone
    earliest_start = _align_timestamp_to_interval(min_timestamp, batch_export)

    return earliest_start, record_count


@temporalio.activity.defn
async def get_backfill_info(inputs: GetBackfillInfoInputs) -> GetBackfillInfoOutputs:
    """Validate backfill parameters and estimate record count.

    For events model: runs combined query for earliest date + count.
    For persons/sessions: runs earliest date only (count returns None for now).

    If no data exists or range contains no data, returns estimated_records_count=0
    (workflow should complete early rather than raising an error).
    """
    bind_contextvars(
        team_id=inputs.team_id,
        batch_export_id=inputs.batch_export_id,
        start_at=inputs.start_at,
        end_at=inputs.end_at,
    )
    logger = LOGGER.bind()

    logger.info("Getting backfill info")

    batch_export = await BatchExport.objects.select_related("destination").aget(id=inputs.batch_export_id)

    model = batch_export.model
    config = batch_export.destination.config
    include_events = config.get("include_events", []) or []
    exclude_events = config.get("exclude_events", []) or []

    # Parse input dates
    start_at = dt.datetime.fromisoformat(inputs.start_at) if inputs.start_at else None
    end_at = dt.datetime.fromisoformat(inputs.end_at) if inputs.end_at else None

    # Build filters clause if filters are configured
    filters_str = ""
    extra_query_parameters: dict[str, typing.Any] = {}
    if batch_export.filters:
        filters_str, extra_query_parameters = await sync_to_async(compose_filters_clause)(
            batch_export.filters, team_id=inputs.team_id
        )
        if filters_str:
            filters_str = f"AND {filters_str}"

    interval_seconds = batch_export.interval_time_delta.total_seconds()

    if model == "events":
        adjusted_start_at, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=start_at,
            end_at=end_at,
            include_events=include_events,
            exclude_events=exclude_events,
            filters_str=filters_str,
            extra_query_parameters=extra_query_parameters,
        )

        if adjusted_start_at is None:
            logger.info(
                "No data exists for backfill",
                team_id=inputs.team_id,
                batch_export_id=inputs.batch_export_id,
                model=model,
            )
            return GetBackfillInfoOutputs(
                adjusted_start_at=inputs.start_at,
                total_records_count=0,
                interval_seconds=interval_seconds,
            )

        if start_at is not None and adjusted_start_at != start_at:
            adjusted_start_at_str = adjusted_start_at.astimezone(start_at.tzinfo).isoformat()
            logger.info(
                "Narrowing backfill start to earliest available data",
                original_start_at=inputs.start_at,
                adjusted_start_at=adjusted_start_at_str,
            )
        else:
            adjusted_start_at_str = inputs.start_at

        return GetBackfillInfoOutputs(
            adjusted_start_at=adjusted_start_at_str,
            total_records_count=record_count,
            interval_seconds=interval_seconds,
        )

    else:
        # For persons/sessions, we don't support estimation yet.
        # Just return None for the count and let the workflow proceed normally.
        #
        # TODO: When implementing persons model support, note:
        # - Need to check 2 tables: `person` and `person_distinct_id2`
        # - Query both tables separately and take the minimum timestamp (more efficient than joining)
        # - Use `_timestamp` field (not `timestamp`)
        # - Filter invalid timestamps with `_timestamp > '2000-01-01'`
        # - Example query pattern:
        #     SELECT toStartOfInterval(MIN(_timestamp), INTERVAL X SECONDS)
        #     FROM person WHERE team_id = Y AND _timestamp > '2000-01-01'
        #     UNION ALL
        #     SELECT toStartOfInterval(MIN(_timestamp), INTERVAL X SECONDS)
        #     FROM person_distinct_id2 WHERE team_id = Y AND _timestamp > '2000-01-01'
        #   Then take min() of results, excluding any 1970 dates (no data indicator).
        logger.info(
            "Backfill info not yet implemented for model, skipping estimation",
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            model=model,
        )
        return GetBackfillInfoOutputs(
            adjusted_start_at=inputs.start_at,
            total_records_count=None,
            interval_seconds=interval_seconds,
        )


@dataclasses.dataclass
class BackfillScheduleInputs:
    """Inputs for the backfill_schedule Activity."""

    schedule_id: str
    start_at: str | None
    end_at: str | None
    frequency_seconds: float
    start_delay: float = 5.0
    backfill_id: str | None = None


def get_utcnow():
    """Return the current time in UTC. This function is only required for mocking during tests,
    because mocking the global datetime breaks Temporal."""
    return dt.datetime.now(dt.UTC)


@temporalio.activity.defn
async def backfill_schedule(inputs: BackfillScheduleInputs) -> None:
    """Temporal Activity to backfill a Temporal Schedule.

    The backfill is broken up into batches of 1. After a backfill batch is
    requested, we wait for it to be done before continuing with the next.

    This activity heartbeats while waiting to allow cancelling an ongoing backfill.
    """
    start_at = dt.datetime.fromisoformat(inputs.start_at) if inputs.start_at else None
    end_at = dt.datetime.fromisoformat(inputs.end_at) if inputs.end_at else None

    async with Heartbeater() as heartbeater:
        client = await connect(
            settings.TEMPORAL_HOST,
            settings.TEMPORAL_PORT,
            settings.TEMPORAL_NAMESPACE,
            settings.TEMPORAL_CLIENT_ROOT_CA,
            settings.TEMPORAL_CLIENT_CERT,
            settings.TEMPORAL_CLIENT_KEY,
        )

        schedule_handle = client.get_schedule_handle(inputs.schedule_id)
        try:
            description = await schedule_handle.describe()
        except temporalio.service.RPCError as e:
            if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                raise TemporalScheduleNotFoundError(inputs.schedule_id)
            else:
                raise

        details = temporalio.activity.info().heartbeat_details
        if details:
            # If we receive details from a previous run, it means we were restarted for some reason.
            # Let's not double-backfill and instead wait for any outstanding runs.
            last_activity_details = HeartbeatDetails(*details)

            workflow_handle = client.get_workflow_handle(last_activity_details.workflow_id)

            heartbeater.details = HeartbeatDetails(
                schedule_id=inputs.schedule_id,
                workflow_id=workflow_handle.id,
                last_batch_data_interval_end=last_activity_details.last_batch_data_interval_end,
            )

            try:
                await workflow_handle.result()
            except temporalio.client.WorkflowFailureError:
                # TODO: Handle failures here instead of in the batch export.
                await asyncio.sleep(inputs.start_delay)

            start_at = dt.datetime.fromisoformat(last_activity_details.last_batch_data_interval_end)

        frequency = dt.timedelta(seconds=inputs.frequency_seconds)

        full_backfill_range = backfill_range(start_at, end_at, frequency)

        for _, backfill_end_at in full_backfill_range:
            if await check_temporal_schedule_exists(client, description.id) is False:
                raise TemporalScheduleNotFoundError(description.id)

            utcnow = get_utcnow()
            backfill_end_at = backfill_end_at.astimezone(dt.UTC)

            if end_at is None and backfill_end_at >= utcnow:
                # This backfill (with no `end_at`) has caught up with real time and should unpause the
                # underlying batch export and exit.
                await sync_to_async(unpause_batch_export)(client, inputs.schedule_id)
                return

            assert isinstance(description.schedule.action, temporalio.client.ScheduleActionStartWorkflow)
            schedule_action: temporalio.client.ScheduleActionStartWorkflow = description.schedule.action

            search_attributes: collections.abc.Sequence[temporalio.common.SearchAttributePair[typing.Any]] = [
                temporalio.common.SearchAttributePair(
                    key=temporalio.common.SearchAttributeKey.for_text("TemporalScheduledById"), value=description.id
                ),
                temporalio.common.SearchAttributePair(
                    key=temporalio.common.SearchAttributeKey.for_datetime("TemporalScheduledStartTime"),
                    value=backfill_end_at,
                ),
            ]

            args = await client.data_converter.decode(schedule_action.args)
            args[0]["backfill_details"] = BackfillDetails(
                backfill_id=inputs.backfill_id,
                is_earliest_backfill=start_at is None,
                start_at=inputs.start_at,
                end_at=inputs.end_at,
            )

            await asyncio.sleep(inputs.start_delay)

            try:
                workflow_handle = await client.start_workflow(
                    schedule_action.workflow,
                    *args,
                    id=f"{description.id}-{backfill_end_at:%Y-%m-%dT%H:%M:%S}Z",
                    task_queue=schedule_action.task_queue,
                    run_timeout=schedule_action.run_timeout,
                    task_timeout=schedule_action.task_timeout,
                    id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    search_attributes=temporalio.common.TypedSearchAttributes(search_attributes=search_attributes),
                )
            except temporalio.exceptions.WorkflowAlreadyStartedError:
                workflow_handle = client.get_workflow_handle(f"{description.id}-{backfill_end_at:%Y-%m-%dT%H:%M:%S}Z")

            details = HeartbeatDetails(
                schedule_id=inputs.schedule_id,
                workflow_id=workflow_handle.id,
                last_batch_data_interval_end=backfill_end_at.isoformat(),
            )

            heartbeater.details = details

            try:
                await workflow_handle.result()
            except temporalio.client.WorkflowFailureError:
                # `WorkflowFailureError` includes cancellations, terminations, timeouts, and errors.
                # Common errors should be handled by the workflow itself (i.e. by retrying an activity).
                # We briefly sleep to allow heartbeating to potentially receive a cancellation request.
                # TODO: Log anyways if we land here.
                await asyncio.sleep(inputs.start_delay)


async def check_temporal_schedule_exists(client: temporalio.client.Client, schedule_id: str) -> bool:
    """Check if Temporal Schedule exists by trying to describe it."""
    handle = client.get_schedule_handle(schedule_id)

    try:
        await handle.describe()
    except temporalio.service.RPCError as e:
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return False
        else:
            raise
    return True


def backfill_range(
    start_at: dt.datetime | None, end_at: dt.datetime | None, step: dt.timedelta
) -> typing.Generator[tuple[dt.datetime | None, dt.datetime], None, None]:
    """Generate range of dates between start_at and end_at."""
    if start_at is None:
        if end_at is None:
            now = get_utcnow()
            latest_end_at = now - dt.timedelta(seconds=now.timestamp() % step.total_seconds())
            yield None, latest_end_at

        else:
            yield None, end_at

        return

    current = start_at

    while end_at is None or current < end_at:
        current_end = current + step

        if end_at and current_end > end_at:
            # Do not yield a range that is less than step.
            # Same as built-in range.
            break

        yield current, current_end

        current = current_end


@temporalio.workflow.defn(name="backfill-batch-export")
class BackfillBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to manage a backfill of a batch export.

    Temporal Schedule backfills are limited in the number of batch periods we can buffer. This limit
    has been confirmed to be less than 1000. So, when triggering a backfill of more than 1000 batch
    periods (about a month for hourly batch exports), we need this Workflow to manage its progress.

    We also report on the progress by updating the BatchExportBackfill model.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BackfillBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return BackfillBatchExportInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: BackfillBatchExportInputs) -> None:
        """Workflow implementation to backfill a BatchExport."""
        bind_contextvars(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            start_at=inputs.start_at,
            end_at=inputs.end_at,
        )
        logger = LOGGER.bind()

        # Step 1: Create backfill model with STARTING status
        backfill_id = await temporalio.workflow.execute_activity(
            create_batch_export_backfill_model,
            CreateBatchExportBackfillInputs(
                team_id=inputs.team_id,
                batch_export_id=inputs.batch_export_id,
                start_at=inputs.start_at,
                end_at=inputs.end_at,
                status=BatchExportBackfill.Status.STARTING,
            ),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        update_inputs = UpdateBatchExportBackfillInputs(
            id=backfill_id, status=BatchExportBackfill.Status.COMPLETED, finished=True
        )
        completed_early = False

        try:
            # Step 2: Get backfill info (validation + estimation)
            backfill_info = await temporalio.workflow.execute_activity(
                get_backfill_info,
                GetBackfillInfoInputs(
                    team_id=inputs.team_id,
                    batch_export_id=inputs.batch_export_id,
                    start_at=inputs.start_at,
                    end_at=inputs.end_at,
                ),
                start_to_close_timeout=dt.timedelta(minutes=30),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=120),
                    maximum_attempts=0,
                ),
            )

            # Step 3: Update backfill with adjusted start and estimated count
            # If total_records_count is 0, complete early; if None (non-events), proceed normally
            should_complete_early = backfill_info.total_records_count == 0

            await temporalio.workflow.execute_activity(
                update_batch_export_backfill_activity,
                UpdateBatchExportBackfillInputs(
                    id=backfill_id,
                    adjusted_start_at=backfill_info.adjusted_start_at,
                    total_records_count=backfill_info.total_records_count,
                    status=(
                        BatchExportBackfill.Status.COMPLETED
                        if should_complete_early
                        else BatchExportBackfill.Status.RUNNING
                    ),
                    finished=should_complete_early,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError"],
                ),
            )

            # Step 4: Early exit if no data to backfill
            if should_complete_early:
                completed_early = True
                return

            start_at = backfill_info.adjusted_start_at
            end_at = inputs.end_at
            interval_seconds = backfill_info.interval_seconds

            if start_at != inputs.start_at:
                logger = logger.bind(adjusted_start_at=start_at)

            logger.info(
                "Creating historical export for batches in range %s - %s",
                start_at,
                end_at,
            )

            # Temporal requires that we set a timeout.
            if end_at is None or start_at is None:
                # Set timeout to a month for now, as unending backfills are an internal feature we are
                # testing for HTTP-based migrations. We'll need to pick a more realistic timeout
                # if we release this to customers.
                start_to_close_timeout = dt.timedelta(days=31)
            else:
                # Allocate 5 minutes per expected number of runs to backfill as a timeout.
                # The 5 minutes are just an assumption and we may tweak this in the future
                backfill_duration = dt.datetime.fromisoformat(end_at) - dt.datetime.fromisoformat(start_at)
                number_of_expected_runs = backfill_duration / dt.timedelta(seconds=interval_seconds)
                start_to_close_timeout = dt.timedelta(minutes=5 * number_of_expected_runs)

            backfill_schedule_inputs = BackfillScheduleInputs(
                schedule_id=inputs.batch_export_id,
                start_at=backfill_info.adjusted_start_at,
                end_at=inputs.end_at,
                frequency_seconds=interval_seconds,
                start_delay=inputs.start_delay,
                backfill_id=backfill_id,
            )

            await temporalio.workflow.execute_activity(
                backfill_schedule,
                backfill_schedule_inputs,
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    non_retryable_error_types=["TemporalScheduleNotFoundError"],
                ),
                start_to_close_timeout=start_to_close_timeout,
                heartbeat_timeout=dt.timedelta(seconds=30),
            )

        except temporalio.exceptions.ActivityError as e:
            if isinstance(e.cause, temporalio.exceptions.CancelledError):
                update_inputs.status = BatchExportBackfill.Status.CANCELLED
            else:
                update_inputs.status = BatchExportBackfill.Status.FAILED

            raise

        except Exception:
            update_inputs.status = BatchExportBackfill.Status.FAILED
            raise

        finally:
            if not completed_early:
                await temporalio.workflow.execute_activity(
                    update_batch_export_backfill_activity,
                    update_inputs,
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=temporalio.common.RetryPolicy(
                        initial_interval=dt.timedelta(seconds=10),
                        maximum_interval=dt.timedelta(seconds=60),
                        maximum_attempts=0,
                        non_retryable_error_types=["NotNullViolation", "IntegrityError"],
                    ),
                )
