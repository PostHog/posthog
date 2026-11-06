from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.exceptions import ChildWorkflowError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.customer_analytics.backend.logic.membership_discovery import (
        MembershipDiscoveryCounts,
        MembershipDiscoveryInput,
        MembershipDiscoveryStore,
        list_membership_discovery_teams,
        record_membership_discovery_team,
        run_membership_discovery,
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

SCHEDULE_ID = "customer-analytics-membership-discovery"
TEAM_WORKFLOW_NAME = "customer-analytics-membership-discovery-team"
MAX_BATCHES_PER_TEAM = 100
MAX_TEAM_PAGES_PER_RUN = 10
TEAM_RUN_BUDGET = timedelta(minutes=10)
COORDINATOR_RUN_BUDGET = timedelta(minutes=45)


@activity.defn
async def list_membership_discovery_teams_activity() -> list[int]:
    return await database_sync_to_async(list_membership_discovery_teams, thread_sensitive=False)(
        MembershipDiscoveryStore()
    )


@activity.defn
async def record_membership_discovery_team_activity(team_id: int) -> None:
    await database_sync_to_async(record_membership_discovery_team, thread_sensitive=False)(team_id)


@activity.defn
async def membership_discovery_activity(input: MembershipDiscoveryInput) -> MembershipDiscoveryCounts:
    async with Heartbeater():
        return await database_sync_to_async(run_membership_discovery, thread_sensitive=False)(
            input, MembershipDiscoveryStore(deadline=get_membership_query_deadline())
        )


@workflow.defn(name=TEAM_WORKFLOW_NAME)
class MembershipDiscoveryTeamWorkflow:
    @workflow.run
    async def run(self, input: MembershipDiscoveryInput) -> MembershipDiscoveryCounts:
        deadline = get_membership_run_deadline(TEAM_RUN_BUDGET)
        total = MembershipDiscoveryCounts()
        for _ in range(MAX_BATCHES_PER_TEAM):
            timeout = get_membership_activity_timeout(deadline)
            if timeout is None:
                break
            result = await workflow.execute_activity(
                membership_discovery_activity,
                input,
                start_to_close_timeout=timeout,
                schedule_to_close_timeout=deadline - workflow.now(),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=BATCH_RETRY_POLICY,
            )
            total = MembershipDiscoveryCounts(
                scanned=total.scanned + result.scanned,
                recovered=total.recovered + result.recovered,
                discovered=total.discovered + result.discovered,
                has_more=result.has_more,
            )
            if not result.has_more or workflow.now() >= deadline:
                break
        return total


@workflow.defn(name=SCHEDULE_ID)
class MembershipDiscoveryWorkflow:
    @workflow.run
    async def run(self) -> None:
        deadline = workflow.now() + COORDINATOR_RUN_BUDGET
        for _ in range(MAX_TEAM_PAGES_PER_RUN):
            if workflow.now() >= deadline:
                break
            teams = await workflow.execute_activity(
                list_membership_discovery_teams_activity,
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
                        MembershipDiscoveryTeamWorkflow.run,
                        MembershipDiscoveryInput(team_id=team_id),
                        id=f"{TEAM_WORKFLOW_NAME}-{team_id}",
                        execution_timeout=min(TEAM_RUN_BUDGET, remaining),
                    )
                except (ChildWorkflowError, WorkflowAlreadyStartedError):
                    workflow.logger.exception("Membership discovery failed for team %s", team_id)
                await workflow.execute_activity(
                    record_membership_discovery_team_activity,
                    team_id,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )


async def create_membership_discovery_schedule(client: Client) -> None:
    await create_membership_schedule(
        client,
        SCHEDULE_ID,
        COORDINATOR_RUN_BUDGET + timedelta(minutes=5),
        "Validate membership discovery before enabling this schedule.",
    )
