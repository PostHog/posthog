import asyncio
import collections.abc
import dataclasses
import datetime as dt
import json
import typing

import temporalio
import temporalio.activity
import temporalio.client
import temporalio.common
import temporalio.exceptions
import temporalio.workflow
from django.conf import settings

from posthog.batch_exports.service import BackfillBatchExportInputs
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
    start_at: str
    end_at: str
    wait_start_at: str

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
    end_at: str
    frequency_seconds: float
    buffer_limit: int = 1
    wait_delay: float = 5.0


@temporalio.activity.defn
async def backfill_schedule(inputs: BackfillScheduleInputs) -> None:
    """Temporal Activity to backfill a Temporal Schedule.

    The backfill is broken up into batches of inputs.buffer_limit size. After a backfill batch is
    requested, we wait for it to be done before continuing with the next.

    This activity heartbeats while waiting to allow cancelling an ongoing backfill.
    """
    start_at = dt.datetime.fromisoformat(inputs.start_at)
    end_at = dt.datetime.fromisoformat(inputs.end_at)

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

        details = HeartbeatDetails(
            schedule_id=inputs.schedule_id,
            start_at=last_activity_details.start_at,
            end_at=last_activity_details.end_at,
            wait_start_at=last_activity_details.wait_start_at,
        )

        await wait_for_schedule_backfill_in_range_with_heartbeat(details, client, heartbeat_timeout, inputs.wait_delay)

        # Update start_at to resume from the end of the period we just waited for
        start_at = dt.datetime.fromisoformat(last_activity_details.end_at)

    handle = client.get_schedule_handle(inputs.schedule_id)

    description = await handle.describe()
    jitter = description.schedule.spec.jitter

    frequency = dt.timedelta(seconds=inputs.frequency_seconds)
    full_backfill_range = backfill_range(start_at, end_at, frequency * inputs.buffer_limit)

    for backfill_start_at, backfill_end_at in full_backfill_range:
        utcnow = dt.datetime.now(dt.timezone.utc)

        if jitter is not None:
            backfill_end_at = backfill_end_at + jitter

        backfill = temporalio.client.ScheduleBackfill(
            start_at=backfill_start_at,
            end_at=backfill_end_at,
            overlap=temporalio.client.ScheduleOverlapPolicy.ALLOW_ALL,
        )
        await handle.backfill(backfill)

        details = HeartbeatDetails(
            schedule_id=inputs.schedule_id,
            start_at=backfill_start_at.isoformat(),
            end_at=backfill_end_at.isoformat(),
            wait_start_at=utcnow.isoformat(),
        )

        await wait_for_schedule_backfill_in_range_with_heartbeat(details, client, heartbeat_timeout, inputs.wait_delay)


async def wait_for_schedule_backfill_in_range_with_heartbeat(
    heartbeat_details: HeartbeatDetails,
    client: temporalio.client.Client,
    heartbeat_timeout: dt.timedelta | None = None,
    wait_delay: float = 5.0,
):
    """Decide if heartbeating is required while waiting for a backfill in range to finish."""
    if heartbeat_timeout:
        wait_func = heartbeat_details.make_activity_heartbeat_while_running(
            wait_for_schedule_backfill_in_range, heartbeat_every=dt.timedelta(seconds=1)
        )
    else:
        wait_func = wait_for_schedule_backfill_in_range

    await wait_func(
        client,
        heartbeat_details.schedule_id,
        dt.datetime.fromisoformat(heartbeat_details.start_at),
        dt.datetime.fromisoformat(heartbeat_details.end_at),
        dt.datetime.fromisoformat(heartbeat_details.wait_start_at),
        wait_delay,
    )


async def wait_for_schedule_backfill_in_range(
    client: temporalio.client.Client,
    schedule_id: str,
    start_at: dt.datetime,
    end_at: dt.datetime,
    now: dt.datetime,
    wait_delay: float = 5.0,
) -> None:
    """Wait for a Temporal Schedule backfill in a date range to be finished.

    We can use the TemporalScheduledById and the TemporalScheduledStartTime to identify the Workflow executions
    runs that fall under this Temporal Schedule's backfill. However, there could be regularly scheduled runs returned
    by a query on just these two fields. So, we take the 'now' argument to provide a lower bound for the Workflow
    execution start time, assuming that backfill runs will have started recently after 'now' whereas regularly
    scheduled runs happened sometime in the past, before 'now'. This should hold true for historical backfills,
    but the heuristic fails for "future backfills", which should not be allowed.

    Raises:
         TemporalScheduleNotFoundError: If we detect the Temporal Schedule we are waiting on doesn't exist.
    """
    if await check_temporal_schedule_exists(client, schedule_id) is False:
        raise TemporalScheduleNotFoundError(schedule_id)

    query = (
        f'TemporalScheduledById="{schedule_id}" '
        f'AND TemporalScheduledStartTime >= "{start_at.isoformat()}" '
        f'AND TemporalScheduledStartTime <= "{end_at.isoformat()}" '
        f'AND StartTime >= "{now.isoformat()}"'
    )

    workflows = [workflow async for workflow in client.list_workflows(query=query)]

    if workflows and check_workflow_executions_not_running(workflows) is True:
        return

    done = False
    while not done:
        await asyncio.sleep(wait_delay)

        if await check_temporal_schedule_exists(client, schedule_id) is False:
            raise TemporalScheduleNotFoundError(schedule_id)

        workflows = [workflow async for workflow in client.list_workflows(query=query)]

        if not workflows:
            # Backfill hasn't started yet.
            continue

        if check_workflow_executions_not_running(workflows) is False:
            continue

        done = True


def check_workflow_executions_not_running(workflow_executions: list[temporalio.client.WorkflowExecution]) -> bool:
    """Check if a list of Worflow Executions has any still running."""
    return all(
        workflow_execution.status != temporalio.client.WorkflowExecutionStatus.RUNNING
        for workflow_execution in workflow_executions
    )


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
    start_at: dt.datetime, end_at: dt.datetime, step: dt.timedelta
) -> typing.Generator[tuple[dt.datetime, dt.datetime], None, None]:
    """Generate range of dates between start_at and end_at."""
    current = start_at

    while current < end_at:
        current_end = current + step

        if current_end > end_at:
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
            status="Running",
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
        update_inputs = UpdateBatchExportBackfillStatusInputs(id=backfill_id, status="Completed")

        frequency_seconds = await temporalio.workflow.execute_activity(
            get_schedule_frequency,
            inputs.batch_export_id,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=0),
        )

        backfill_duration = dt.datetime.fromisoformat(inputs.end_at) - dt.datetime.fromisoformat(inputs.start_at)
        number_of_expected_runs = backfill_duration / dt.timedelta(seconds=frequency_seconds)

        backfill_schedule_inputs = BackfillScheduleInputs(
            schedule_id=inputs.batch_export_id,
            start_at=inputs.start_at,
            end_at=inputs.end_at,
            frequency_seconds=frequency_seconds,
            buffer_limit=inputs.buffer_limit,
            wait_delay=inputs.wait_delay,
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
                # Temporal requires that we set a timeout.
                # Allocate 5 minutes per expected number of runs to backfill as a timeout.
                # The 5 minutes are just an assumption and we may tweak this in the future
                start_to_close_timeout=dt.timedelta(minutes=5 * number_of_expected_runs),
                heartbeat_timeout=dt.timedelta(minutes=2),
            )

        except temporalio.exceptions.ActivityError as e:
            if isinstance(e.cause, temporalio.exceptions.CancelledError):
                update_inputs.status = "Cancelled"
            else:
                update_inputs.status = "Failed"

            raise

        except Exception:
            update_inputs.status = "Failed"
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
