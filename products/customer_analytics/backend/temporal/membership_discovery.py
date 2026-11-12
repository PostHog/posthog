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
    from products.customer_analytics.backend.logic.membership_metrics import MembershipTimings

from products.customer_analytics.backend.temporal.membership_common import (
    BATCH_RETRY_POLICY,
    HEARTBEAT_TIMEOUT,
    MIN_TEAM_RUN_BUDGET,
    create_membership_schedule,
    get_membership_activity_timeout,
    get_membership_query_deadline,
    get_membership_run_deadline,
    record_membership_run,
)

SCHEDULE_ID = "customer-analytics-membership-discovery"
TEAM_WORKFLOW_NAME = "customer-analytics-membership-discovery-team"
MAX_BATCHES_PER_TEAM = 100
MAX_TEAM_PAGES_PER_RUN = 10
TEAM_RUN_BUDGET = timedelta(minutes=10)
COORDINATOR_RUN_BUDGET = timedelta(minutes=45)


@activity.defn
async def list_membership_discovery_teams_activity() -> list[int]:
    with MembershipTimings(job="discovery").measure("list_teams"):
        return await database_sync_to_async(list_membership_discovery_teams, thread_sensitive=False)(
            MembershipDiscoveryStore()
        )


@activity.defn
async def record_membership_discovery_team_activity(team_id: int) -> None:
    with MembershipTimings(job="discovery").measure("write_team_checkpoint"):
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
        with record_membership_run("discovery", "team", team_id=input.team_id) as summary:
            summary.stop_reason = "batch_limit"
            summary.add_counts(batches=0, scanned=0, recovered=0, discovered=0)
            for _ in range(MAX_BATCHES_PER_TEAM):
                timeout = get_membership_activity_timeout(deadline)
                if timeout is None:
                    summary.stop_reason = "time_budget"
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
                summary.add_counts(
                    batches=1, scanned=result.scanned, recovered=result.recovered, discovered=result.discovered
                )
                if not result.has_more:
                    summary.stop_reason = "completed"
                    break
                if workflow.now() >= deadline:
                    summary.stop_reason = "time_budget"
                    break
        return total


@workflow.defn(name=SCHEDULE_ID)
class MembershipDiscoveryWorkflow:
    @workflow.run
    async def run(self) -> None:
        deadline = workflow.now() + COORDINATOR_RUN_BUDGET
        with record_membership_run("discovery", "coordinator") as summary:
            summary.stop_reason = "team_page_limit"
            summary.add_counts(
                teams_completed=0, teams_failed=0, teams_already_running=0, scanned=0, recovered=0, discovered=0
            )
            for _ in range(MAX_TEAM_PAGES_PER_RUN):
                if workflow.now() >= deadline:
                    summary.stop_reason = "time_budget"
                    break
                teams = await workflow.execute_activity(
                    list_membership_discovery_teams_activity,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                if not teams:
                    summary.stop_reason = "completed"
                    break
                for team_id in teams:
                    remaining = deadline - workflow.now()
                    if remaining <= MIN_TEAM_RUN_BUDGET:
                        summary.stop_reason = "time_budget"
                        return
                    try:
                        result = await workflow.execute_child_workflow(
                            MembershipDiscoveryTeamWorkflow.run,
                            MembershipDiscoveryInput(team_id=team_id),
                            id=f"{TEAM_WORKFLOW_NAME}-{team_id}",
                            execution_timeout=min(TEAM_RUN_BUDGET, remaining),
                        )
                        summary.add_counts(
                            teams_completed=1,
                            scanned=result.scanned,
                            recovered=result.recovered,
                            discovered=result.discovered,
                        )
                    except WorkflowAlreadyStartedError:
                        summary.add_counts(teams_already_running=1)
                        workflow.logger.exception("Membership discovery already running for team %s", team_id)
                    except ChildWorkflowError:
                        summary.add_counts(teams_failed=1)
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
