import json
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.common import RetryPolicy
from temporalio.exceptions import ChildWorkflowError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.dataclasses import frozen
    from posthog.scheduling.jitter import deterministic_offset
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists

    from products.customer_analytics.backend.logic.membership_cleanup import (
        MembershipCleanupCounts,
        MembershipCleanupInput,
        MembershipCleanupStore,
        list_membership_cleanup_teams,
        run_membership_cleanup,
    )

SCHEDULE_ID = "customer-analytics-membership-cleanup"
TEAM_WORKFLOW_NAME = "customer-analytics-membership-cleanup-team"


@frozen
class MembershipCleanupScheduleInput:
    dry_run: bool = True
    delete_team_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if len(self.delete_team_ids) > 25 or any(team_id <= 0 for team_id in self.delete_team_ids):
            raise ValueError("Membership cleanup permits at most 25 positive deletion team IDs")


@activity.defn
async def list_membership_cleanup_teams_activity() -> list[int]:
    return await database_sync_to_async(list_membership_cleanup_teams, thread_sensitive=False)(MembershipCleanupStore())


@activity.defn
async def membership_cleanup_activity(input: MembershipCleanupInput) -> MembershipCleanupCounts:
    async with Heartbeater():
        return await database_sync_to_async(run_membership_cleanup, thread_sensitive=False)(
            input, MembershipCleanupStore()
        )


@workflow.defn(name=TEAM_WORKFLOW_NAME)
class MembershipCleanupTeamWorkflow:
    @workflow.run
    async def run(self, input: MembershipCleanupInput) -> MembershipCleanupCounts:
        return await workflow.execute_activity(
            membership_cleanup_activity,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn(name=SCHEDULE_ID)
class MembershipCleanupWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> MembershipCleanupScheduleInput:
        return MembershipCleanupScheduleInput(**json.loads(inputs[0])) if inputs else MembershipCleanupScheduleInput()

    @workflow.run
    async def run(self, input: MembershipCleanupScheduleInput) -> None:
        teams = await workflow.execute_activity(
            list_membership_cleanup_teams_activity,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        for team_id in teams:
            try:
                await workflow.execute_child_workflow(
                    MembershipCleanupTeamWorkflow.run,
                    MembershipCleanupInput(
                        team_id=team_id, dry_run=input.dry_run, delete_team_ids=input.delete_team_ids
                    ),
                    id=f"{TEAM_WORKFLOW_NAME}-{team_id}",
                    execution_timeout=timedelta(minutes=35),
                )
            except (ChildWorkflowError, WorkflowAlreadyStartedError):
                workflow.logger.exception("Membership cleanup failed for team %s", team_id)


async def create_membership_cleanup_schedule(client: Client) -> None:
    if await a_schedule_exists(client, SCHEDULE_ID):
        return
    await a_create_schedule(
        client,
        SCHEDULE_ID,
        Schedule(
            action=ScheduleActionStartWorkflow(
                SCHEDULE_ID,
                MembershipCleanupScheduleInput(),
                id=SCHEDULE_ID,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                execution_timeout=timedelta(hours=16),
                retry_policy=RetryPolicy(maximum_attempts=1),
            ),
            spec=ScheduleSpec(
                intervals=[
                    ScheduleIntervalSpec(
                        every=timedelta(hours=1), offset=deterministic_offset(SCHEDULE_ID, timedelta(hours=1))
                    )
                ]
            ),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            state=ScheduleState(paused=True, note="Validate dry-run cleanup before enabling deletion."),
        ),
        trigger_immediately=False,
    )
