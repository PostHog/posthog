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

    from posthog.scheduling.jitter import deterministic_offset
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists

    from products.customer_analytics.backend.logic.membership_discovery import (
        MembershipDiscoveryCounts,
        MembershipDiscoveryInput,
        MembershipDiscoveryStore,
        list_membership_discovery_teams,
        record_membership_discovery_team,
        run_membership_discovery,
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
            input, MembershipDiscoveryStore()
        )


@workflow.defn(name=TEAM_WORKFLOW_NAME)
class MembershipDiscoveryTeamWorkflow:
    @workflow.run
    async def run(self, input: MembershipDiscoveryInput) -> MembershipDiscoveryCounts:
        deadline = workflow.now() + TEAM_RUN_BUDGET
        total = MembershipDiscoveryCounts()
        for _ in range(MAX_BATCHES_PER_TEAM):
            result = await workflow.execute_activity(
                membership_discovery_activity,
                input,
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
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
                if remaining <= timedelta():
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
    if await a_schedule_exists(client, SCHEDULE_ID):
        return
    await a_create_schedule(
        client,
        SCHEDULE_ID,
        Schedule(
            action=ScheduleActionStartWorkflow(
                SCHEDULE_ID,
                id=SCHEDULE_ID,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                execution_timeout=COORDINATOR_RUN_BUDGET + timedelta(minutes=5),
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
            state=ScheduleState(paused=True, note="Validate membership discovery before enabling this schedule."),
        ),
        trigger_immediately=False,
    )
