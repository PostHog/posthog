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

from posthog.batch_exports.models import BatchExport, BatchExportBackfill
from posthog.batch_exports.service import BackfillBatchExportInputs, BackfillDetails, unpause_batch_export
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import connect
from posthog.temporal.common.heartbeat import Heartbeater

from products.batch_exports.backend.temporal.batch_exports import (
    CreateBatchExportBackfillInputs,
    UpdateBatchExportBackfillStatusInputs,
    create_batch_export_backfill_model,
    update_batch_export_backfill_model_status,
)


class TemporalScheduleNotFoundError(Exception):
    """Exception raised when a Temporal Schedule is not found."""

    def __init__(self, schedule_id: str):
        super().__init__(f"The Temporal Schedule {schedule_id} was not found (maybe it was deleted?)")


class HeartbeatDetails(typing.NamedTuple):
    """Details sent over in a Temporal Activity heartbeat."""

    schedule_id: str
    workflow_id: str
    last_batch_data_interval_end: str


@temporalio.activity.defn
async def get_batch_export_interval(batch_export_id: str) -> float:
    """Return a batch export's interval in seconds."""
    batch_export = await BatchExport.objects.aget(id=batch_export_id)
    return batch_export.interval_time_delta.total_seconds()


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

        interval_seconds = await temporalio.workflow.execute_activity(
            get_batch_export_interval,
            inputs.batch_export_id,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=0, non_retryable_error_types=["TemporalScheduleNotFoundError"]
            ),
        )

        # Temporal requires that we set a timeout.
        if inputs.end_at is None or inputs.start_at is None:
            # Set timeout to a month for now, as unending backfills are an internal feature we are
            # testing for HTTP-based migrations. We'll need to pick a more realistic timeout
            # if we release this to customers.
            start_to_close_timeout = dt.timedelta(days=31)
        else:
            # Allocate 5 minutes per expected number of runs to backfill as a timeout.
            # The 5 minutes are just an assumption and we may tweak this in the future
            backfill_duration = dt.datetime.fromisoformat(inputs.end_at) - dt.datetime.fromisoformat(inputs.start_at)
            number_of_expected_runs = backfill_duration / dt.timedelta(seconds=interval_seconds)
            start_to_close_timeout = dt.timedelta(minutes=5 * number_of_expected_runs)

        backfill_schedule_inputs = BackfillScheduleInputs(
            schedule_id=inputs.batch_export_id,
            start_at=inputs.start_at,
            end_at=inputs.end_at,
            frequency_seconds=interval_seconds,
            start_delay=inputs.start_delay,
            backfill_id=backfill_id,
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
