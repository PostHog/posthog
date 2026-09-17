from __future__ import annotations

import json
import asyncio
from typing import Literal
from uuid import UUID

from temporalio import activity, workflow
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from datetime import datetime, timedelta

    from django.conf import settings
    from django.utils import timezone

    import structlog

    from posthog.dataclasses import frozen
    from posthog.exceptions_capture import capture_exception
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

    from products.customer_analytics.backend.logic.account_track_rules import (
        AccountTrackRuleRunError,
        AccountTrackRuleValidationError,
        AccountTrackRuleVersionConflict,
        create_account_track_rule_run,
        fail_account_track_rule_run,
        list_enabled_account_track_rule_configs,
        process_next_account_track_rule_batch,
    )
    from products.customer_analytics.backend.metrics import record_account_track_rule_coordinator
    from products.customer_analytics.backend.models import AccountTrackRuleRunTrigger

ACCOUNT_TRACK_RULE_WORKFLOW_NAME = "customer-analytics-account-track-rule-evaluation"
ACCOUNT_TRACK_RULE_COORDINATOR_WORKFLOW_NAME = "customer-analytics-account-track-rule-coordinator"
ACCOUNT_TRACK_RULE_COORDINATOR_SCHEDULE_ID = "customer-analytics-account-track-rule-coordinator-schedule"
ACCOUNT_TRACK_RULE_COORDINATOR_PAGE_SIZE = 100
ACCOUNT_TRACK_RULE_SCHEDULE_HOUR_UTC = 6
ACCOUNT_TRACK_RULE_RECENT_SUCCESS_MAX_AGE = timedelta(hours=36)

logger = structlog.get_logger(__name__)


@frozen
class AccountTrackRuleEvaluationInput:
    team_id: int
    run_id: str
    config_version: int
    trigger: str = AccountTrackRuleRunTrigger.MANUAL


@frozen
class AccountTrackRuleEvaluationOutput:
    status: str
    processed: int


@frozen
class AccountTrackRuleCoordinatorInput:
    pass


@frozen
class AccountTrackRuleCoordinatorPageInput:
    after_team_id: int = 0


@frozen
class AccountTrackRuleCoordinatorTeam:
    team_id: int
    config_version: int


@frozen
class AccountTrackRuleCoordinatorPage:
    teams: tuple[AccountTrackRuleCoordinatorTeam, ...]
    next_team_id: int | None
    overdue_teams: int
    oldest_success_age_seconds: float


@frozen
class AccountTrackRuleScheduledRunInput:
    team_id: int
    config_version: int
    coordinator_run_id: str


@frozen
class AccountTrackRuleScheduledRun:
    status: Literal["created", "existing", "disabled", "stale", "invalid"]
    run_id: str | None
    config_version: int


@frozen
class AccountTrackRuleCoordinatorObservation:
    outcome: Literal["completed", "failed"]
    duration_seconds: float
    pages: int
    enabled_teams: int
    started_children: int
    overlapping_children: int
    skipped_children: int
    overdue_teams: int
    oldest_success_age_seconds: float


@frozen
class AccountTrackRuleCoordinatorOutput:
    pages: int
    enabled_teams: int
    started_children: int
    overlapping_children: int
    skipped_children: int
    overdue_teams: int


class AccountTrackRuleRunsOverdue(RuntimeError):
    pass


def account_track_rule_workflow_id(team_id: int) -> str:
    return f"customer-analytics-account-track-rules-{team_id}"


@activity.defn
async def account_track_rule_process_batch_activity(
    input: AccountTrackRuleEvaluationInput,
) -> AccountTrackRuleEvaluationOutput:
    try:
        async with Heartbeater():
            result = await database_sync_to_async(process_next_account_track_rule_batch, thread_sensitive=False)(
                input.team_id, UUID(input.run_id)
            )
        return AccountTrackRuleEvaluationOutput(status=result.status, processed=result.processed)
    except Exception as error:
        logger.error(  # noqa: TRY400 — exception text can contain rule values
            "account_track_rule_batch_failed",
            team_id=input.team_id,
            run_id=input.run_id,
            config_version=input.config_version,
            trigger=input.trigger,
            status="failed",
            exception_type=type(error).__name__,
        )
        capture_exception(
            error,
            {
                "team_id": input.team_id,
                "run_id": input.run_id,
                "config_version": input.config_version,
                "stage": "process_batch",
            },
        )
        raise


@activity.defn
async def account_track_rule_fail_run_activity(input: AccountTrackRuleEvaluationInput) -> None:
    await database_sync_to_async(fail_account_track_rule_run, thread_sensitive=False)(input.team_id, UUID(input.run_id))


@activity.defn
async def account_track_rule_collect_configs_activity(
    input: AccountTrackRuleCoordinatorPageInput,
) -> AccountTrackRuleCoordinatorPage:
    page = await database_sync_to_async(list_enabled_account_track_rule_configs, thread_sensitive=False)(
        after_team_id=input.after_team_id,
        limit=ACCOUNT_TRACK_RULE_COORDINATOR_PAGE_SIZE,
    )
    now = timezone.now()
    teams: list[AccountTrackRuleCoordinatorTeam] = []
    overdue_teams = 0
    oldest_success_age_seconds = 0.0

    for config in page.configs:
        teams.append(
            AccountTrackRuleCoordinatorTeam(
                team_id=config.team_id,
                config_version=config.config_version,
            )
        )
        freshness_anchors = [
            ("enabled", config.enabled_at),
            ("first_run", config.first_run_at),
            ("success", config.last_success_at),
        ]
        available_anchors: list[tuple[str, datetime]] = [
            (source, timestamp) for source, timestamp in freshness_anchors if timestamp is not None
        ]
        if not available_anchors:
            overdue_teams += 1
            logger.error(
                "account_track_rule_enabled_team_overdue",
                team_id=config.team_id,
                config_version=config.config_version,
                trigger=AccountTrackRuleRunTrigger.SCHEDULED,
                status="overdue",
                freshness_source="missing",
                freshness_age_seconds=None,
            )
            continue

        freshness_source, freshness_anchor = max(available_anchors, key=lambda anchor: anchor[1])
        freshness_age_seconds = max(0.0, (now - freshness_anchor).total_seconds())
        oldest_success_age_seconds = max(oldest_success_age_seconds, freshness_age_seconds)
        if freshness_age_seconds > ACCOUNT_TRACK_RULE_RECENT_SUCCESS_MAX_AGE.total_seconds():
            overdue_teams += 1
            logger.error(
                "account_track_rule_enabled_team_overdue",
                team_id=config.team_id,
                config_version=config.config_version,
                trigger=AccountTrackRuleRunTrigger.SCHEDULED,
                status="overdue",
                freshness_source=freshness_source,
                freshness_age_seconds=freshness_age_seconds,
            )

    logger.info(
        "account_track_rule_coordinator_page_collected",
        after_team_id=input.after_team_id,
        next_team_id=page.next_team_id,
        enabled_teams=len(teams),
        overdue_teams=overdue_teams,
    )
    return AccountTrackRuleCoordinatorPage(
        teams=tuple(teams),
        next_team_id=page.next_team_id,
        overdue_teams=overdue_teams,
        oldest_success_age_seconds=oldest_success_age_seconds,
    )


@activity.defn
async def account_track_rule_create_scheduled_run_activity(
    input: AccountTrackRuleScheduledRunInput,
) -> AccountTrackRuleScheduledRun:
    try:
        run, created = await database_sync_to_async(create_account_track_rule_run, thread_sensitive=False)(
            team_id=input.team_id,
            idempotency_key=UUID(input.coordinator_run_id),
            user_id=None,
            trigger=AccountTrackRuleRunTrigger.SCHEDULED,
            expected_config_version=input.config_version,
        )
    except AccountTrackRuleVersionConflict:
        logger.info(
            "account_track_rule_scheduled_run_skipped",
            team_id=input.team_id,
            config_version=input.config_version,
            trigger=AccountTrackRuleRunTrigger.SCHEDULED,
            status="stale",
        )
        return AccountTrackRuleScheduledRun(status="stale", run_id=None, config_version=input.config_version)
    except AccountTrackRuleRunError:
        logger.info(
            "account_track_rule_scheduled_run_skipped",
            team_id=input.team_id,
            config_version=input.config_version,
            trigger=AccountTrackRuleRunTrigger.SCHEDULED,
            status="disabled",
        )
        return AccountTrackRuleScheduledRun(status="disabled", run_id=None, config_version=input.config_version)
    except AccountTrackRuleValidationError as error:
        logger.error(  # noqa: TRY400 - exception text can contain rule values
            "account_track_rule_scheduled_run_invalid",
            team_id=input.team_id,
            config_version=input.config_version,
            trigger=AccountTrackRuleRunTrigger.SCHEDULED,
            status="invalid",
        )
        capture_exception(
            error,
            {
                "team_id": input.team_id,
                "config_version": input.config_version,
                "stage": "create_scheduled_run",
            },
        )
        return AccountTrackRuleScheduledRun(status="invalid", run_id=None, config_version=input.config_version)

    status: Literal["created", "existing"] = "created" if created else "existing"
    logger.info(
        "account_track_rule_scheduled_run_queued",
        team_id=input.team_id,
        run_id=str(run.id),
        config_version=run.config_version,
        trigger=run.trigger,
        status=status,
    )
    return AccountTrackRuleScheduledRun(status=status, run_id=str(run.id), config_version=run.config_version)


@activity.defn
async def account_track_rule_observe_coordinator_activity(input: AccountTrackRuleCoordinatorObservation) -> None:
    record_account_track_rule_coordinator(
        outcome=input.outcome,
        duration_seconds=input.duration_seconds,
        enabled_teams=input.enabled_teams,
        started_children=input.started_children,
        overlapping_children=input.overlapping_children,
        skipped_children=input.skipped_children,
        overdue_teams=input.overdue_teams,
        oldest_success_age_seconds=input.oldest_success_age_seconds,
    )
    log = logger.error if input.outcome == "failed" else logger.info
    log(
        "account_track_rule_coordinator_finished",
        outcome=input.outcome,
        duration_seconds=input.duration_seconds,
        pages=input.pages,
        enabled_teams=input.enabled_teams,
        started_children=input.started_children,
        overlapping_children=input.overlapping_children,
        skipped_children=input.skipped_children,
        overdue_teams=input.overdue_teams,
        oldest_success_age_seconds=input.oldest_success_age_seconds,
    )
    if input.overdue_teams:
        capture_exception(
            AccountTrackRuleRunsOverdue("Enabled Account Track Rules teams are overdue."),
            {
                "overdue_teams": input.overdue_teams,
                "oldest_success_age_seconds": input.oldest_success_age_seconds,
            },
        )


@workflow.defn(name=ACCOUNT_TRACK_RULE_WORKFLOW_NAME)
class AccountTrackRuleEvaluationWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> AccountTrackRuleEvaluationInput:
        return AccountTrackRuleEvaluationInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, input: AccountTrackRuleEvaluationInput) -> AccountTrackRuleEvaluationOutput:
        try:
            while True:
                result = await workflow.execute_activity(
                    account_track_rule_process_batch_activity,
                    input,
                    start_to_close_timeout=timedelta(minutes=10),
                    heartbeat_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5)),
                )
                if result.status not in {"pending", "running"}:
                    return result
        except asyncio.CancelledError:
            await workflow.execute_activity(
                account_track_rule_fail_run_activity,
                input,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise
        except Exception:
            await workflow.execute_activity(
                account_track_rule_fail_run_activity,
                input,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise


@workflow.defn(name=ACCOUNT_TRACK_RULE_COORDINATOR_WORKFLOW_NAME)
class AccountTrackRuleCoordinatorWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> AccountTrackRuleCoordinatorInput:
        if not inputs:
            return AccountTrackRuleCoordinatorInput()
        return AccountTrackRuleCoordinatorInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, _input: AccountTrackRuleCoordinatorInput) -> AccountTrackRuleCoordinatorOutput:
        started_at = workflow.now()
        coordinator_run_id = workflow.info().run_id
        after_team_id = 0
        pages = 0
        enabled_teams = 0
        started_children = 0
        overlapping_children = 0
        skipped_children = 0
        overdue_teams = 0
        oldest_success_age_seconds = 0.0

        try:
            while True:
                page = await workflow.execute_activity(
                    account_track_rule_collect_configs_activity,
                    AccountTrackRuleCoordinatorPageInput(after_team_id=after_team_id),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                pages += 1
                enabled_teams += len(page.teams)
                overdue_teams += page.overdue_teams
                oldest_success_age_seconds = max(
                    oldest_success_age_seconds,
                    page.oldest_success_age_seconds,
                )

                for team in page.teams:
                    scheduled_run = await workflow.execute_activity(
                        account_track_rule_create_scheduled_run_activity,
                        AccountTrackRuleScheduledRunInput(
                            team_id=team.team_id,
                            config_version=team.config_version,
                            coordinator_run_id=coordinator_run_id,
                        ),
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    if scheduled_run.run_id is None:
                        skipped_children += 1
                        continue

                    evaluation_input = AccountTrackRuleEvaluationInput(
                        team_id=team.team_id,
                        run_id=scheduled_run.run_id,
                        config_version=scheduled_run.config_version,
                        trigger=AccountTrackRuleRunTrigger.SCHEDULED,
                    )
                    try:
                        await workflow.start_child_workflow(
                            AccountTrackRuleEvaluationWorkflow.run,
                            evaluation_input,
                            id=account_track_rule_workflow_id(team.team_id),
                            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                            execution_timeout=timedelta(hours=24),
                            retry_policy=RetryPolicy(maximum_attempts=1),
                        )
                        started_children += 1
                    except WorkflowAlreadyStartedError:
                        overlapping_children += 1
                        await workflow.execute_activity(
                            account_track_rule_fail_run_activity,
                            evaluation_input,
                            start_to_close_timeout=timedelta(minutes=2),
                            retry_policy=RetryPolicy(maximum_attempts=3),
                        )

                if page.next_team_id is None:
                    break
                after_team_id = page.next_team_id
        except Exception:
            await self._observe(
                outcome="failed",
                started_at=started_at,
                pages=pages,
                enabled_teams=enabled_teams,
                started_children=started_children,
                overlapping_children=overlapping_children,
                skipped_children=skipped_children,
                overdue_teams=overdue_teams,
                oldest_success_age_seconds=oldest_success_age_seconds,
            )
            raise

        await self._observe(
            outcome="completed",
            started_at=started_at,
            pages=pages,
            enabled_teams=enabled_teams,
            started_children=started_children,
            overlapping_children=overlapping_children,
            skipped_children=skipped_children,
            overdue_teams=overdue_teams,
            oldest_success_age_seconds=oldest_success_age_seconds,
        )
        return AccountTrackRuleCoordinatorOutput(
            pages=pages,
            enabled_teams=enabled_teams,
            started_children=started_children,
            overlapping_children=overlapping_children,
            skipped_children=skipped_children,
            overdue_teams=overdue_teams,
        )

    async def _observe(
        self,
        *,
        outcome: Literal["completed", "failed"],
        started_at: datetime,
        pages: int,
        enabled_teams: int,
        started_children: int,
        overlapping_children: int,
        skipped_children: int,
        overdue_teams: int,
        oldest_success_age_seconds: float,
    ) -> None:
        await workflow.execute_activity(
            account_track_rule_observe_coordinator_activity,
            AccountTrackRuleCoordinatorObservation(
                outcome=outcome,
                duration_seconds=(workflow.now() - started_at).total_seconds(),
                pages=pages,
                enabled_teams=enabled_teams,
                started_children=started_children,
                overlapping_children=overlapping_children,
                skipped_children=skipped_children,
                overdue_teams=overdue_teams,
                oldest_success_age_seconds=oldest_success_age_seconds,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


def _build_account_track_rule_coordinator_schedule(state: ScheduleState) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            ACCOUNT_TRACK_RULE_COORDINATOR_WORKFLOW_NAME,
            AccountTrackRuleCoordinatorInput(),
            id=ACCOUNT_TRACK_RULE_COORDINATOR_WORKFLOW_NAME,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 06:00 UTC",
                    hour=[ScheduleRange(start=ACCOUNT_TRACK_RULE_SCHEDULE_HOUR_UTC)],
                    minute=[ScheduleRange(start=0)],
                )
            ]
        ),
        state=state,
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def create_account_track_rule_coordinator_schedule(client: Client) -> None:
    if await a_schedule_exists(client, ACCOUNT_TRACK_RULE_COORDINATOR_SCHEDULE_ID):
        description = await client.get_schedule_handle(ACCOUNT_TRACK_RULE_COORDINATOR_SCHEDULE_ID).describe()
        schedule = _build_account_track_rule_coordinator_schedule(description.schedule.state)
        await a_update_schedule(client, ACCOUNT_TRACK_RULE_COORDINATOR_SCHEDULE_ID, schedule)
        return

    schedule = _build_account_track_rule_coordinator_schedule(
        ScheduleState(
            paused=True,
            note="Paused for controlled Account Track Rules rollout.",
        )
    )
    await a_create_schedule(
        client,
        ACCOUNT_TRACK_RULE_COORDINATOR_SCHEDULE_ID,
        schedule,
        trigger_immediately=False,
    )
