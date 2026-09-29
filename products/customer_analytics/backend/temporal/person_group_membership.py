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
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    import structlog

    from posthog.dataclasses import frozen
    from posthog.exceptions_capture import capture_exception
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.client import async_connect
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

    from products.customer_analytics.backend.logic.person_group_membership import (
        MembershipBackfill,
        MembershipStep,
        advance_membership_backfill,
        fail_membership_backfill,
        membership_candidate_page,
        sync_membership_team,
    )
    from products.customer_analytics.backend.logic.person_group_membership_metrics import (
        CHUNK_DURATION,
        SYNC_LAG,
        SYNC_TEAMS,
    )

COORDINATOR_NAME = "customer-analytics-person-group-membership-coordinator"
BACKFILL_NAME = "customer-analytics-person-group-membership-backfill"
SCHEDULE_ID = f"{COORDINATOR_NAME}-schedule"
logger = structlog.get_logger(__name__)


@frozen
class MembershipCoordinator:
    after_team_id: int = 0
    dry_run: bool = True


def membership_backfill_workflow_id(team_id: int) -> str:
    return f"{BACKFILL_NAME}-{team_id}"


async def start_membership_backfill(client: Client, input: MembershipBackfill) -> bool:
    try:
        await client.start_workflow(
            PersonGroupMembershipBackfillWorkflow.run,
            input,
            id=membership_backfill_workflow_id(input.team_id),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            execution_timeout=timedelta(days=7),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        return True
    except WorkflowAlreadyStartedError:
        return False


@activity.defn
async def sync_membership_page_activity(input: MembershipCoordinator) -> int | None:
    async with Heartbeater():
        ids = await database_sync_to_async(membership_candidate_page, thread_sensitive=False)(input.after_team_id)
        client = await async_connect() if ids and not input.dry_run else None
        oldest_lag = 0.0
        for team_id in ids:
            SYNC_TEAMS.labels("candidate", str(input.dry_run)).inc()
            try:
                result = await database_sync_to_async(sync_membership_team, thread_sensitive=False)(
                    team_id, dry_run=input.dry_run
                )
                if result.enabled:
                    SYNC_TEAMS.labels("enabled", str(input.dry_run)).inc()
                if result.changed:
                    SYNC_TEAMS.labels("changed", str(input.dry_run)).inc()
                oldest_lag = max(oldest_lag, result.lag_seconds)
                if result.needs_backfill and client is not None:
                    await start_membership_backfill(
                        client, MembershipBackfill(team_id=team_id, config_version=result.config_version, dry_run=False)
                    )
            except Exception as error:
                SYNC_TEAMS.labels("failed", str(input.dry_run)).inc()
                capture_exception(error)
                logger.exception("membership_team_sync_failed", team_id=team_id)
        SYNC_LAG.set(oldest_lag)
    return ids[-1] if ids else None


@activity.defn
async def advance_membership_backfill_activity(input: MembershipBackfill) -> MembershipStep:
    with CHUNK_DURATION.time():
        async with Heartbeater():
            return await database_sync_to_async(advance_membership_backfill, thread_sensitive=False)(input)


@activity.defn
async def fail_membership_backfill_activity(input: MembershipBackfill) -> None:
    await database_sync_to_async(fail_membership_backfill, thread_sensitive=False)(input, "ActivityError")


@workflow.defn(name=BACKFILL_NAME)
class PersonGroupMembershipBackfillWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> MembershipBackfill:
        return MembershipBackfill(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, input: MembershipBackfill) -> None:
        try:
            for _ in range(100):
                step = await workflow.execute_activity(
                    advance_membership_backfill_activity,
                    input,
                    start_to_close_timeout=timedelta(minutes=15),
                    heartbeat_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5)),
                )
                if step.status == "done":
                    return
                if step.wait_until is not None:
                    await workflow.sleep(max(timedelta(), step.wait_until - workflow.now()))
            workflow.continue_as_new(input)
        except Exception:
            await workflow.execute_activity(
                fail_membership_backfill_activity,
                input,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise


@workflow.defn(name=COORDINATOR_NAME)
class PersonGroupMembershipCoordinatorWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> MembershipCoordinator:
        return MembershipCoordinator(**json.loads(inputs[0])) if inputs else MembershipCoordinator()

    @workflow.run
    async def run(self, input: MembershipCoordinator) -> None:
        cursor = await workflow.execute_activity(
            sync_membership_page_activity,
            input,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if cursor is not None:
            workflow.continue_as_new(MembershipCoordinator(after_team_id=cursor, dry_run=input.dry_run))


def build_membership_coordinator_schedule(state: ScheduleState) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            COORDINATOR_NAME,
            MembershipCoordinator(),
            id=COORDINATOR_NAME,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=15))]),
        state=state,
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def create_person_group_membership_coordinator_schedule(client: Client) -> None:
    if await a_schedule_exists(client, SCHEDULE_ID):
        description = await client.get_schedule_handle(SCHEDULE_ID).describe()
        schedule = build_membership_coordinator_schedule(description.schedule.state)
        # Keep the write opt-in across deploys, as well as the operator's paused state.
        schedule.action = description.schedule.action
        await a_update_schedule(client, SCHEDULE_ID, schedule)
        return
    await a_create_schedule(
        client,
        SCHEDULE_ID,
        build_membership_coordinator_schedule(
            ScheduleState(paused=True, note="Paused until live membership ingestion is deployed.")
        ),
        trigger_immediately=False,
    )
