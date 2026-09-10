from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

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
    from datetime import datetime, timedelta

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
BACKFILL_PAGES_PER_RUN = 100
GOOGLE_WORKSPACE_RETRY_DELAY = timedelta(hours=1)


@dataclass
class CalendarSyncCoordinatorInput:
    pass


@dataclass
class CalendarSyncInput:
    integration_id: int = 0
    team_id: int = 0


@dataclass(frozen=True, kw_only=True)
class GoogleAccountBackfillInput:
    integration_id: int
    team_id: int
    start_at: str
    end_at: str
    calendar_completed: bool = False
    calendar_page_token: str | None = None
    calendar_fetched: int = 0
    calendar_upserted: int = 0
    gmail_page_token: str | None = None
    gmail_fetched: int = 0


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


@dataclass(frozen=True, kw_only=True)
class CalendarBackfillPageOutput:
    next_page_token: str | None
    fetched: int
    upserted: int


@dataclass(frozen=True, kw_only=True)
class GoogleAccountEmailBackfillOutput:
    next_page_token: str | None
    fetched: int


@dataclass(frozen=True, kw_only=True)
class GoogleAccountBackfillOutput:
    calendar_fetched: int
    calendar_upserted: int
    gmail_fetched: int


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


def _create_google_workspace_budget_error(integration_id: int, team_id: int, error: Exception) -> ApplicationError:
    from products.customer_analytics.backend.logic.calendar_sync import mark_calendar_sync_retrying  # noqa: PLC0415

    mark_calendar_sync_retrying(integration_id, team_id, GOOGLE_WORKSPACE_RETRY_DELAY)
    return ApplicationError(str(error), next_retry_delay=GOOGLE_WORKSPACE_RETRY_DELAY)


def _run_calendar_sync(input: CalendarSyncInput) -> CalendarSyncOutput:
    # Deferred: the sync logic pulls requests/HogQL layers that don't belong in the sandbox.
    from posthog.egress.google_workspace.transport import GoogleWorkspaceEgressBudgetExhausted  # noqa: PLC0415

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
    except GoogleWorkspaceEgressBudgetExhausted as error:
        raise _create_google_workspace_budget_error(input.integration_id, input.team_id, error) from error
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


def _run_calendar_backfill(input: GoogleAccountBackfillInput) -> CalendarBackfillPageOutput:
    from posthog.egress.google_workspace.transport import GoogleWorkspaceEgressBudgetExhausted  # noqa: PLC0415

    from products.customer_analytics.backend.logic.calendar_sync import (  # noqa: PLC0415
        CalendarSyncError,
        sync_calendar_integration_backfill_page,
    )

    try:
        result = sync_calendar_integration_backfill_page(
            input.integration_id,
            input.team_id,
            start_at=datetime.fromisoformat(input.start_at),
            end_at=datetime.fromisoformat(input.end_at),
            page_token=input.calendar_page_token,
        )
    except CalendarSyncError as error:
        raise ApplicationError(str(error), non_retryable="refresh failed" in str(error).lower()) from error
    except GoogleWorkspaceEgressBudgetExhausted as error:
        raise _create_google_workspace_budget_error(input.integration_id, input.team_id, error) from error
    return CalendarBackfillPageOutput(
        next_page_token=result.next_page_token,
        fetched=result.counts.fetched,
        upserted=result.counts.upserted,
    )


@activity.defn
async def calendar_backfill_integration_activity(input: GoogleAccountBackfillInput) -> CalendarBackfillPageOutput:
    async with Heartbeater():
        return await database_sync_to_async(_run_calendar_backfill, thread_sensitive=False)(input)


def _run_google_account_email_backfill(input: GoogleAccountBackfillInput) -> GoogleAccountEmailBackfillOutput:
    from posthog.egress.google_workspace.transport import GoogleWorkspaceEgressBudgetExhausted  # noqa: PLC0415

    from products.conversations.backend.facade import api as conversations  # noqa: PLC0415
    from products.customer_analytics.backend.logic.calendar_sync import (  # noqa: PLC0415
        mark_calendar_sync_completed,
        mark_calendar_sync_started,
    )

    try:
        result = conversations.sync_google_account_email_backfill_batch(
            input.integration_id,
            input.team_id,
            start_at=datetime.fromisoformat(input.start_at),
            end_at=datetime.fromisoformat(input.end_at),
            page_token=input.gmail_page_token,
        )
    except conversations.GoogleAccountEmailSyncError as error:
        raise ApplicationError(str(error), non_retryable="refresh failed" in str(error).lower()) from error
    except GoogleWorkspaceEgressBudgetExhausted as error:
        raise _create_google_workspace_budget_error(input.integration_id, input.team_id, error) from error
    if result.next_page_token:
        mark_calendar_sync_started(input.integration_id, input.team_id)
    else:
        mark_calendar_sync_completed(input.integration_id, input.team_id)
    return GoogleAccountEmailBackfillOutput(next_page_token=result.next_page_token, fetched=result.fetched)


@activity.defn
async def google_account_email_backfill_activity(
    input: GoogleAccountBackfillInput,
) -> GoogleAccountEmailBackfillOutput:
    async with Heartbeater():
        return await database_sync_to_async(_run_google_account_email_backfill, thread_sensitive=False)(input)


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


@workflow.defn(name="customer-analytics-google-account-backfill")
class GoogleAccountBackfillWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> GoogleAccountBackfillInput:
        return GoogleAccountBackfillInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, input: GoogleAccountBackfillInput) -> GoogleAccountBackfillOutput:
        current_input = input
        pages_processed = 0
        while not current_input.calendar_completed:
            calendar_result = await workflow.execute_activity(
                calendar_backfill_integration_activity,
                current_input,
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=10)),
            )
            current_input = replace(
                current_input,
                calendar_completed=calendar_result.next_page_token is None,
                calendar_page_token=calendar_result.next_page_token,
                calendar_fetched=current_input.calendar_fetched + calendar_result.fetched,
                calendar_upserted=current_input.calendar_upserted + calendar_result.upserted,
            )
            pages_processed += 1
            if not current_input.calendar_completed and (
                pages_processed >= BACKFILL_PAGES_PER_RUN or workflow.info().is_continue_as_new_suggested()
            ):
                workflow.continue_as_new(current_input)

        pages_processed = 0
        while True:
            gmail_result = await workflow.execute_activity(
                google_account_email_backfill_activity,
                current_input,
                start_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=5, initial_interval=timedelta(minutes=1)),
            )
            current_input = replace(
                current_input,
                gmail_page_token=gmail_result.next_page_token,
                gmail_fetched=current_input.gmail_fetched + gmail_result.fetched,
            )
            if gmail_result.next_page_token is None:
                return GoogleAccountBackfillOutput(
                    calendar_fetched=current_input.calendar_fetched,
                    calendar_upserted=current_input.calendar_upserted,
                    gmail_fetched=current_input.gmail_fetched,
                )

            pages_processed += 1
            if pages_processed >= BACKFILL_PAGES_PER_RUN or workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(current_input)


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
