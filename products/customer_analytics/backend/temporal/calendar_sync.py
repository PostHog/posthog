from __future__ import annotations

import json
from dataclasses import dataclass, field

from temporalio import activity, workflow
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from datetime import timedelta

    from django.conf import settings

    import structlog

    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

logger = structlog.get_logger(__name__)

CALENDAR_SYNC_COORDINATOR_SCHEDULE_ID = "customer-analytics-calendar-sync-coordinator-schedule"
CALENDAR_SYNC_COORDINATOR_WORKFLOW_NAME = "customer-analytics-calendar-sync-coordinator"
COORDINATOR_INTERVAL_MINUTES = 60
MAX_SYNCS_PER_RUN = 200


@dataclass
class CalendarSyncCoordinatorInput:
    pass


@dataclass
class CalendarSyncInput:
    integration_id: int = 0
    team_id: int = 0


@dataclass
class CollectCalendarIntegrationsOutput:
    integrations: list[CalendarSyncInput] = field(default_factory=list)


@dataclass
class CalendarSyncOutput:
    fetched: int = 0
    upserted: int = 0
    cancelled: int = 0
    skipped: int = 0
    matched: int = 0
    unmatched: int = 0


@dataclass
class CalendarSyncCoordinatorOutput:
    due_count: int = 0
    started_count: int = 0
    skipped_count: int = 0


def _collect_calendar_integrations() -> list[CalendarSyncInput]:
    # Deferred: keeps Django models out of the workflow sandbox import path.
    from posthog.models.integration import Integration  # noqa: PLC0415

    rows = Integration.objects.filter(kind="google-calendar").values_list("id", "team_id")[:MAX_SYNCS_PER_RUN]
    return [CalendarSyncInput(integration_id=row[0], team_id=row[1]) for row in rows]


@activity.defn
async def calendar_sync_collect_integrations_activity(
    _input: CalendarSyncCoordinatorInput,
) -> CollectCalendarIntegrationsOutput:
    """List connected Google Calendars across teams; connecting is the opt-in."""
    async with Heartbeater():
        integrations = await database_sync_to_async(_collect_calendar_integrations, thread_sensitive=False)()
    logger.info("calendar_sync coordinator: connected calendars", count=len(integrations))
    return CollectCalendarIntegrationsOutput(integrations=integrations)


def _run_calendar_sync(input: CalendarSyncInput) -> CalendarSyncOutput:
    # Deferred: the sync logic pulls requests/HogQL layers that don't belong in the sandbox.
    from products.conversations.backend.facade import api as conversations  # noqa: PLC0415
    from products.customer_analytics.backend.logic.calendar_sync import (  # noqa: PLC0415
        CalendarSyncError,
        sync_calendar_integration,
    )

    try:
        counts = sync_calendar_integration(input.integration_id, input.team_id)
        conversations.sync_google_account_email(input.integration_id, input.team_id)
    except (CalendarSyncError, conversations.GoogleAccountEmailSyncError) as e:
        # A dead refresh token can't heal by retrying; the user must reconnect.
        raise ApplicationError(str(e), non_retryable="refresh failed" in str(e).lower()) from e
    return CalendarSyncOutput(
        fetched=counts.fetched,
        upserted=counts.upserted,
        cancelled=counts.cancelled,
        skipped=counts.skipped,
        matched=counts.matched,
        unmatched=len(counts.unmatched_emails),
    )


@activity.defn
async def calendar_sync_integration_activity(input: CalendarSyncInput) -> CalendarSyncOutput:
    """Sync one connected calendar: backfill or incremental, filter, upsert, match."""
    async with Heartbeater():
        return await database_sync_to_async(_run_calendar_sync, thread_sensitive=False)(input)


@workflow.defn(name="customer-analytics-calendar-sync")
class CalendarSyncWorkflow:
    """Single-activity sync of one calendar. Event payloads never cross the activity
    boundary; only counters return."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CalendarSyncInput:
        return CalendarSyncInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, input: CalendarSyncInput) -> CalendarSyncOutput:
        return await workflow.execute_activity(
            calendar_sync_integration_activity,
            input,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
        )


@workflow.defn(name=CALENDAR_SYNC_COORDINATOR_WORKFLOW_NAME)
class CalendarSyncCoordinatorWorkflow:
    """Hourly coordinator: one child per connected calendar.

    Child ids are deterministic per integration, so overlapping ticks can't sync the
    same calendar concurrently (start fails with WorkflowAlreadyStartedError while a
    child runs). ALLOW_DUPLICATE lets the next tick start a fresh run once the
    previous one closed - syncs are cursor-based and idempotent, so reruns are safe.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CalendarSyncCoordinatorInput:
        if not inputs:
            return CalendarSyncCoordinatorInput()
        return CalendarSyncCoordinatorInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, _input: CalendarSyncCoordinatorInput) -> CalendarSyncCoordinatorOutput:
        result = await workflow.execute_activity(
            calendar_sync_collect_integrations_activity,
            _input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        started = 0
        skipped = 0
        for item in result.integrations:
            child_id = f"google-calendar-sync-{item.integration_id}"
            try:
                await workflow.start_child_workflow(
                    CalendarSyncWorkflow.run,
                    item,
                    id=child_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                workflow.logger.info(
                    "calendar_sync coordinator: child already running",
                    extra={"child_id": child_id},
                )
                skipped += 1

        return CalendarSyncCoordinatorOutput(
            due_count=len(result.integrations), started_count=started, skipped_count=skipped
        )


async def create_calendar_sync_coordinator_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            CALENDAR_SYNC_COORDINATOR_WORKFLOW_NAME,
            CalendarSyncCoordinatorInput(),
            id=f"{CALENDAR_SYNC_COORDINATOR_WORKFLOW_NAME}-workflow",
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=COORDINATOR_INTERVAL_MINUTES))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, CALENDAR_SYNC_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, CALENDAR_SYNC_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, CALENDAR_SYNC_COORDINATOR_SCHEDULE_ID, schedule, trigger_immediately=False)
