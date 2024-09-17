import asyncio
import collections.abc
import dataclasses
import datetime as dt
import json
import typing
import zoneinfo

import temporalio
import temporalio.activity
import temporalio.client
import temporalio.common
import temporalio.exceptions
import temporalio.workflow
from asgiref.sync import sync_to_async
from django.conf import settings

from posthog.batch_exports.models import BatchExportBackfill
from posthog.batch_exports.service import BackfillBatchExportInputs, unpause_batch_export
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.batch_exports.batch_exports import (
    CreateBatchExportBackfillInputs,
    UpdateBatchExportBackfillStatusInputs,
    create_batch_export_backfill_model,
    update_batch_export_backfill_model_status,
)
from posthog.temporal.common.client import connect


class TemporalScheduleNotFoundError(Exception):
    """Exception raised when a Temporal Schedule is not found."""

    def __init__(self, schedule_id: str):
        super().__init__(f"The Temporal Schedule {schedule_id} was not found (maybe it was deleted?)")


class HeartbeatDetails(typing.NamedTuple):
    """Details sent over in a Temporal Activity heartbeat."""

    schedule_id: str
    workflow_id: str
    last_batch_data_interval_end: str

    def make_activity_heartbeat_while_running(
        self, function_to_run: collections.abc.Callable, heartbeat_every: dt.timedelta
    ) -> collections.abc.Callable[..., collections.abc.Coroutine]:
        """Return a callable that returns a coroutine that heartbeats with these HeartbeatDetails.

        The returned callable wraps 'function_to_run' while heartbeating every 'heartbeat_every'
        seconds.
        """

        async def heartbeat() -> None:
            """Heartbeat every 'heartbeat_every' seconds."""
            while True:
                await asyncio.sleep(heartbeat_every.total_seconds())
                temporalio.activity.heartbeat(self)

        async def heartbeat_while_running(*args, **kwargs):
            """Wrap 'function_to_run' to asynchronously heartbeat while awaiting."""
            heartbeat_task = asyncio.create_task(heartbeat())

            try:
                return await function_to_run(*args, **kwargs)
            finally:
                heartbeat_task.cancel()
                await asyncio.wait([heartbeat_task])

        return heartbeat_while_running


@temporalio.activity.defn
async def get_schedule_frequency(schedule_id: str) -> float:
    """Return a Temporal Schedule's frequency.

    This assumes that the Schedule has one interval set.

    Raises:
         TemporalScheduleNotFoundError: If the Temporal Schedule whose frequency we are trying to get doesn't exist.
    """
    client = await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_CLIENT_ROOT_CA,
        settings.TEMPORAL_CLIENT_CERT,
        settings.TEMPORAL_CLIENT_KEY,
    )

    handle = client.get_schedule_handle(schedule_id)

    try:
        desc = await handle.describe()
    except temporalio.service.RPCError as e:
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            raise TemporalScheduleNotFoundError(schedule_id)
        else:
            raise

    interval = desc.schedule.spec.intervals[0]
    return interval.every.total_seconds()


@dataclasses.dataclass
class BackfillScheduleInputs:
    """Inputs for the backfill_schedule Activity."""

    schedule_id: str
    start_at: str
    end_at: str | None
    inserted_at_interval_start: str | None = None
    frequency_seconds: float
    start_delay: float = 5.0


def get_utcnow():
    """Return the current time in UTC. This function is only required for mocking during tests,
    because mocking the global datetime breaks Temporal."""
    return dt.datetime.now(dt.UTC)


def adjust_bound_datetime_to_schedule_time_zone(
    bound_dt: dt.datetime, schedule_time_zone_name: str | None, frequency: dt.timedelta
) -> dt.datetime:
    """Adjust the bound datetime of a backfill to match the schedule's timezone.

    First the happy paths:
    1. The bound datetime's timezone is the same as the schedule's.
    2. The schedule's timezone is `None` and the bound datetime's timezone is UTC.
      * Temporal defaults to UTC if `time_zone_name` is not set.

    In both cases, we simply return.

    However, in the event that the schedule's timezone and the bound datetime's timezone do
    not match we must assume that either:
    1. The project's timezone has changed from when the batch export was created.
    2. The batch export is naive (i.e. the schedule's timezone is `None`, which defaults to "UTC").

    There are two solutions depending on the schedule's frequency:
    * Daily exports always run at midnight, so we can just replace the bound datetime's timezone
      with the schedule's timezone.
    * Other frequencies are converted to the timezone instead.

    The second solution is pretty optimal as users will be able to backfill as they see things in the
    UI: Run times will match in the list view with the bounds of the backfill, as the UI will re-convert
    timestamps back into the project's timezone.

    The first solution is not optimal as users see that the runs in the list are not happening at
    midnight, and the days selected to backfill may be off by 1. Unfortunately, when selecting a date in
    the frontend with day granularity we set the time component to 00:00:00. Ideally, we would set it
    to the offset to the schedule's midnight (in whatever timezone the schedule is at). But I can't
    figure out a way to do it, and it may require implementing further work to support switching when the
    schedule runs to other than midnight.
    """
    if bound_dt.tzinfo is None:
        raise ValueError("Only timezone aware datetime objects are supported")

    if (schedule_time_zone_name is not None and schedule_time_zone_name == bound_dt.tzname()) or (
        schedule_time_zone_name is None and bound_dt.tzname() == "UTC"
    ):
        return bound_dt

    if schedule_time_zone_name is None:
        required_timezone = zoneinfo.ZoneInfo("UTC")

    else:
        required_timezone = zoneinfo.ZoneInfo(schedule_time_zone_name)

    if frequency == dt.timedelta(days=1):
        bound_dt = bound_dt.replace(tzinfo=required_timezone)
    else:
        bound_dt = bound_dt.astimezone(required_timezone)

    return bound_dt


@temporalio.activity.defn
async def backfill_schedule(inputs: BackfillScheduleInputs) -> None:
    """Temporal Activity to backfill a Temporal Schedule.

    The backfill is broken up into batches of 1. After a backfill batch is
    requested, we wait for it to be done before continuing with the next.

    This activity heartbeats while waiting to allow cancelling an ongoing backfill.
    """
    start_at = dt.datetime.fromisoformat(inputs.start_at)
    end_at = dt.datetime.fromisoformat(inputs.end_at) if inputs.end_at else None

    client = await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_CLIENT_ROOT_CA,
        settings.TEMPORAL_CLIENT_CERT,
        settings.TEMPORAL_CLIENT_KEY,
    )

    heartbeat_timeout = temporalio.activity.info().heartbeat_timeout

    details = temporalio.activity.info().heartbeat_details

    if details:
        # If we receive details from a previous run, it means we were restarted for some reason.
        # Let's not double-backfill and instead wait for any outstanding runs.
        last_activity_details = HeartbeatDetails(*details[0])

        workflow_handle = client.get_workflow_handle(last_activity_details.workflow_id)
        details = HeartbeatDetails(
            schedule_id=inputs.schedule_id,
            workflow_id=workflow_handle.id,
            last_batch_data_interval_end=last_activity_details.last_batch_data_interval_end,
        )

        await wait_for_workflow_with_heartbeat(details, workflow_handle, heartbeat_timeout)

        # Update start_at to resume from the end of the period we just waited for
        start_at = dt.datetime.fromisoformat(last_activity_details.last_batch_data_interval_end)

    schedule_handle = client.get_schedule_handle(inputs.schedule_id)

    description = await schedule_handle.describe()
    frequency = dt.timedelta(seconds=inputs.frequency_seconds)

    start_at = adjust_bound_datetime_to_schedule_time_zone(
        start_at,
        schedule_time_zone_name=description.schedule.spec.time_zone_name,
        frequency=frequency,
    )
    if end_at is not None:
        end_at = adjust_bound_datetime_to_schedule_time_zone(
            end_at, schedule_time_zone_name=description.schedule.spec.time_zone_name, frequency=frequency
        )

    full_backfill_range = backfill_range(start_at, end_at, frequency)
    inserted_at_interval_start = (
        dt.datetime.fromisoformat(inputs.inserted_at_interval_start) if inputs.inserted_at_interval_start else None
    )

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

        schedule_action: temporalio.client.ScheduleActionStartWorkflow = description.schedule.action

        search_attributes = [
            temporalio.common.SearchAttributePair(
                key=temporalio.common.SearchAttributeKey.for_text("TemporalScheduledById"), value=description.id
            ),
            temporalio.common.SearchAttributePair(
                key=temporalio.common.SearchAttributeKey.for_datetime("TemporalScheduledStartTime"),
                value=backfill_end_at,
            ),
            temporalio.common.SearchAttributePair(
                key=temporalio.common.SearchAttributeKey.for_datetime("TemporalLastInsertedAtStart"),
                value=inserted_at_interval_start,
            ),
        ]

        args = await client.data_converter.decode(schedule_action.args)
        args[0]["is_backfill"] = True

        await asyncio.sleep(inputs.start_delay)

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
        details = HeartbeatDetails(
            schedule_id=inputs.schedule_id,
            workflow_id=workflow_handle.id,
            last_batch_data_interval_end=backfill_end_at.isoformat(),
        )
        temporalio.activity.heartbeat(details)

        await wait_for_workflow_with_heartbeat(details, workflow_handle, heartbeat_timeout, inputs.start_delay)


async def wait_for_workflow_with_heartbeat(
    heartbeat_details: HeartbeatDetails,
    workflow_handle: temporalio.client.WorkflowHandle,
    heartbeat_timeout: dt.timedelta | None = None,
    sleep_on_failure: float = 5.0,
):
    """Decide if heartbeating is required while waiting for a backfill in range to finish."""
    if heartbeat_timeout:
        wait_func = heartbeat_details.make_activity_heartbeat_while_running(
            workflow_handle.result, heartbeat_every=dt.timedelta(seconds=1)
        )
    else:
        wait_func = workflow_handle.result

    try:
        await wait_func()
    except temporalio.client.WorkflowFailureError:
        # `WorkflowFailureError` includes cancellations, terminations, timeouts, and errors.
        # Common errors should be handled by the workflow itself (i.e. by retrying an activity).
        # We briefly sleep to allow heartbeating to potentially receive a cancellation request.
        # TODO: Log anyways if we land here.
        await asyncio.sleep(sleep_on_failure)


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
    start_at: dt.datetime, end_at: dt.datetime | None, step: dt.timedelta
) -> typing.Generator[tuple[dt.datetime, dt.datetime], None, None]:
    """Generate range of dates between start_at and end_at."""
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
        create_batch_export_backfill_inputs = CreateBatchExportBackfillInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            start_at=inputs.start_at,
            end_at=inputs.end_at,
            status=BatchExportBackfill.Status.RUNNING,
        )

        backfill_id = await temporalio.workflow.execute_activity(
            create_batch_export_backfill_model,
            create_batch_export_backfill_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )
        update_inputs = UpdateBatchExportBackfillStatusInputs(
            id=backfill_id, status=BatchExportBackfill.Status.COMPLETED
        )

        frequency_seconds = await temporalio.workflow.execute_activity(
            get_schedule_frequency,
            inputs.batch_export_id,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=0, non_retryable_error_types=["TemporalScheduleNotFoundError"]
            ),
        )

        # Temporal requires that we set a timeout.
        if inputs.end_at is None:
            # Set timeout to a month for now, as unending backfills are an internal feature we are
            # testing for HTTP-based migrations. We'll need to pick a more realistic timeout
            # if we release this to customers.
            start_to_close_timeout = dt.timedelta(days=31)
        else:
            # Allocate 5 minutes per expected number of runs to backfill as a timeout.
            # The 5 minutes are just an assumption and we may tweak this in the future
            backfill_duration = dt.datetime.fromisoformat(inputs.end_at) - dt.datetime.fromisoformat(inputs.start_at)
            number_of_expected_runs = backfill_duration / dt.timedelta(seconds=frequency_seconds)
            start_to_close_timeout = dt.timedelta(minutes=5 * number_of_expected_runs)

        backfill_schedule_inputs = BackfillScheduleInputs(
            schedule_id=inputs.batch_export_id,
            start_at=inputs.start_at,
            end_at=inputs.end_at,
            inserted_at_interval_start=inputs.inserted_at_interval_start,
            frequency_seconds=frequency_seconds,
            start_delay=inputs.start_delay,
        )
        try:
            await temporalio.workflow.execute_activity(
                backfill_schedule,
                backfill_schedule_inputs,
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    non_retryable_error_types=["TemporalScheduleNotFoundError"],
                ),
                start_to_close_timeout=start_to_close_timeout,
                heartbeat_timeout=dt.timedelta(minutes=2),
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
            await temporalio.workflow.execute_activity(
                update_batch_export_backfill_model_status,
                update_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError"],
                ),
            )
