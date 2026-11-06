import json
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.exceptions import ChildWorkflowError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from posthog.dataclasses import frozen
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.customer_analytics.backend.logic.membership_deletion import (
        MembershipDeletionCounts,
        MembershipDeletionInput,
        MembershipDeletionStore,
        list_membership_deletion_teams,
        record_membership_deletion_team,
        run_membership_deletion,
    )

from products.customer_analytics.backend.temporal.membership_common import (
    BATCH_RETRY_POLICY,
    HEARTBEAT_TIMEOUT,
    MIN_TEAM_RUN_BUDGET,
    create_membership_schedule,
    get_membership_activity_timeout,
    get_membership_query_deadline,
    get_membership_run_deadline,
)

SCHEDULE_ID = "customer-analytics-membership-deletion"
TEAM_WORKFLOW_NAME = "customer-analytics-membership-deletion-team"
MAX_BATCHES_PER_TEAM = 100
MAX_TEAM_PAGES_PER_RUN = 10
TEAM_RUN_BUDGET = timedelta(minutes=10)
COORDINATOR_RUN_BUDGET = timedelta(minutes=45)


@frozen
class MembershipDeletionScheduleInput:
    dry_run: bool = True
    delete_team_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if len(self.delete_team_ids) > 25 or any(team_id <= 0 for team_id in self.delete_team_ids):
            raise ValueError("Membership deletion permits at most 25 positive deletion team IDs")


@activity.defn
async def list_membership_deletion_teams_activity() -> list[int]:
    return await database_sync_to_async(list_membership_deletion_teams, thread_sensitive=False)()


@activity.defn
async def record_membership_deletion_team_activity(team_id: int) -> None:
    await database_sync_to_async(record_membership_deletion_team, thread_sensitive=False)(team_id)


@activity.defn
async def membership_deletion_activity(input: MembershipDeletionInput) -> MembershipDeletionCounts:
    async with Heartbeater():
        return await database_sync_to_async(run_membership_deletion, thread_sensitive=False)(
            input, MembershipDeletionStore(deadline=get_membership_query_deadline())
        )


@workflow.defn(name=TEAM_WORKFLOW_NAME)
class MembershipDeletionTeamWorkflow:
    @workflow.run
    async def run(self, input: MembershipDeletionInput) -> MembershipDeletionCounts:
        deadline = get_membership_run_deadline(TEAM_RUN_BUDGET)
        total = MembershipDeletionCounts()
        for _ in range(MAX_BATCHES_PER_TEAM):
            timeout = get_membership_activity_timeout(deadline)
            if timeout is None:
                break
            result = await workflow.execute_activity(
                membership_deletion_activity,
                input,
                start_to_close_timeout=timeout,
                schedule_to_close_timeout=deadline - workflow.now(),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=BATCH_RETRY_POLICY,
            )
            total = MembershipDeletionCounts(
                checked=total.checked + result.checked,
                recovered=total.recovered + result.recovered,
                overdue=total.overdue + result.overdue,
                deleted=total.deleted + result.deleted,
                has_more=result.has_more,
            )
            if not result.has_more or workflow.now() >= deadline:
                break
        return total


@workflow.defn(name=SCHEDULE_ID)
class MembershipDeletionWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> MembershipDeletionScheduleInput:
        return MembershipDeletionScheduleInput(**json.loads(inputs[0])) if inputs else MembershipDeletionScheduleInput()

    @workflow.run
    async def run(self, input: MembershipDeletionScheduleInput) -> None:
        deadline = workflow.now() + COORDINATOR_RUN_BUDGET
        for _ in range(MAX_TEAM_PAGES_PER_RUN):
            if workflow.now() >= deadline:
                break
            teams = await workflow.execute_activity(
                list_membership_deletion_teams_activity,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if not teams:
                break
            for team_id in teams:
                remaining = deadline - workflow.now()
                if remaining <= MIN_TEAM_RUN_BUDGET:
                    return
                try:
                    await workflow.execute_child_workflow(
                        MembershipDeletionTeamWorkflow.run,
                        MembershipDeletionInput(
                            team_id=team_id, dry_run=input.dry_run, delete_team_ids=input.delete_team_ids
                        ),
                        id=f"{TEAM_WORKFLOW_NAME}-{team_id}",
                        execution_timeout=min(TEAM_RUN_BUDGET, remaining),
                    )
                except (ChildWorkflowError, WorkflowAlreadyStartedError):
                    workflow.logger.exception("Membership deletion failed for team %s", team_id)
                await workflow.execute_activity(
                    record_membership_deletion_team_activity,
                    team_id,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )


async def create_membership_deletion_schedule(client: Client) -> None:
    await create_membership_schedule(
        client,
        SCHEDULE_ID,
        COORDINATOR_RUN_BUDGET + timedelta(minutes=5),
        "Validate dry-run cleanup before enabling deletion.",
        MembershipDeletionScheduleInput(),
    )
