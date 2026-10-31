import json
from dataclasses import replace
from datetime import timedelta
from threading import Event
from time import monotonic

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
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    import structlog

    from posthog.dataclasses import frozen
    from posthog.scheduling.jitter import deterministic_offset
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

    from products.customer_analytics.backend.logic.membership_backfill import (
        MembershipBackfillService,
        MembershipCursor,
        MembershipStep,
        MembershipSyncPage,
        MembershipTeam,
    )
    from products.customer_analytics.backend.metrics import record_membership_operation

COORDINATOR_NAME = "customer-analytics-membership-coordinator"
BACKFILL_NAME = "customer-analytics-membership-backfill"
SCHEDULE_ID = "customer-analytics-membership-coordinator-schedule"
LOGGER = structlog.get_logger(__name__)


@frozen
class MembershipCoordinatorInput:
    after_team_id: int = 0
    dry_run: bool = True


@frozen
class MembershipFailure:
    team_id: int
    version: int
    error_type: str
    account_keys: tuple[str, ...] = ()
    dry_run: bool = False


@frozen
class MembershipObservation:
    input: MembershipTeam
    run_id: str
    event: str
    status: str
    error_type: str = ""


@frozen
class MembershipRunStatus:
    team_id: int
    run_id: str
    status: str
    dry_run: bool
    account_count: int
    cursor: MembershipCursor | None
    error_type: str = ""


def get_membership_workflow_id(team_id: int) -> str:
    return f"{BACKFILL_NAME}-{team_id}"


@activity.defn
async def sync_membership_page_activity(input: MembershipCoordinatorInput) -> MembershipSyncPage:
    stopped = Event()
    service = MembershipBackfillService(deadline=monotonic() + 585, should_stop=stopped.is_set)
    try:
        async with Heartbeater():
            page = await database_sync_to_async(service.sync_page, thread_sensitive=False)(
                input.after_team_id, dry_run=input.dry_run
            )
        record_membership_operation("sync", "candidates", page.candidates)
        record_membership_operation("sync", "enabled", page.enabled)
        record_membership_operation("sync", "changed", page.changed)
        return page
    except Exception:
        record_membership_operation("sync", "failed")
        raise
    finally:
        stopped.set()


@activity.defn
async def prepare_membership_backfill_activity(input: MembershipTeam) -> MembershipTeam:
    stopped = Event()
    service = MembershipBackfillService(deadline=monotonic() + 105, should_stop=stopped.is_set)
    try:
        async with Heartbeater():
            return await database_sync_to_async(service.prepare_backfill, thread_sensitive=False)(input)
    finally:
        stopped.set()


@activity.defn
async def backfill_membership_batch_activity(input: MembershipTeam) -> MembershipStep:
    started = monotonic()
    stopped = Event()
    try:
        async with Heartbeater():
            result = await database_sync_to_async(
                MembershipBackfillService.process_activity_batch, thread_sensitive=False
            )(input, deadline=started + 285, should_stop=stopped.is_set)
        if result.cursor:
            result.cursor.last_batch_duration_seconds = monotonic() - started
            if result.lag_seconds is not None:
                result.cursor.lag_seconds = result.lag_seconds
        record_membership_operation("backfill", result.status, rows=result.rows, lag_seconds=result.lag_seconds)
        return result
    except Exception:
        record_membership_operation("backfill", "failed")
        raise
    finally:
        stopped.set()


@activity.defn
async def fail_membership_backfill_activity(input: MembershipFailure) -> None:
    if not input.account_keys and not input.dry_run:
        await database_sync_to_async(MembershipBackfillService.fail, thread_sensitive=False)(
            input.team_id, input.version, input.error_type
        )


@activity.defn
async def observe_membership_backfill_activity(observation: MembershipObservation) -> None:
    input = observation.input
    cursor = input.cursor
    duration = (
        (activity.info().current_attempt_scheduled_time - cursor.started_at).total_seconds()
        if cursor and cursor.started_at
        else 0
    )
    LOGGER.info(
        "customer_analytics.membership_backfill",
        backfill_event=observation.event,
        backfill_run_id=observation.run_id,
        team_id=input.team_id,
        status=observation.status,
        dry_run=input.dry_run,
        account_scope="selected" if input.account_keys else "all",
        account_count=len(input.account_keys),
        accounts_completed=cursor.accounts_completed if cursor else 0,
        windows_completed=cursor.windows_completed if cursor else 0,
        rows_written=cursor.rows_written if cursor else 0,
        rows_found=cursor.rows_found if cursor else 0,
        duration_seconds=max(0, duration),
        batch_duration_seconds=cursor.last_batch_duration_seconds if cursor else 0,
        lag_seconds=cursor.lag_seconds if cursor else 0,
        error_type=observation.error_type,
    )


@workflow.defn(name=BACKFILL_NAME)
class MembershipBackfillWorkflow:
    def __init__(self) -> None:
        self.input = MembershipTeam(team_id=0)
        self.status = "starting"
        self.error_type = ""
        self.resume_requested = False
        self.cancel_requested = False
        self.run_id = ""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> MembershipTeam:
        return MembershipTeam(**json.loads(inputs[0]))

    @workflow.query
    def get_status(self) -> MembershipRunStatus:
        return MembershipRunStatus(
            team_id=self.input.team_id,
            run_id=self.run_id,
            status=self.status,
            dry_run=self.input.dry_run,
            account_count=len(self.input.account_keys),
            cursor=self.input.cursor,
            error_type=self.error_type,
        )

    @workflow.signal
    def resume(self) -> None:
        if self.status == "failed":
            self.resume_requested = True

    @workflow.signal
    def cancel(self) -> None:
        self.cancel_requested = True

    async def observe(self, event: str) -> None:
        try:
            await workflow.execute_activity(
                observe_membership_backfill_activity,
                MembershipObservation(
                    input=self.input, run_id=self.run_id, event=event, status=self.status, error_type=self.error_type
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError:
            workflow.logger.warning("Membership backfill observation failed", extra={"backfill_event": event})

    async def process_batch(self) -> MembershipStep:
        if not self.input.cursor and not self.input.version and not self.input.dry_run:
            self.input = await workflow.execute_activity(
                prepare_membership_backfill_activity,
                self.input,
                start_to_close_timeout=timedelta(minutes=2),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        result = await workflow.execute_activity(
            backfill_membership_batch_activity,
            self.input,
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        self.input = replace(self.input, cursor=result.cursor)
        self.status = result.status
        self.error_type = ""
        await self.observe("progress")
        return replace(result, status="cancelled") if self.cancel_requested else result

    @workflow.run
    async def run(self, input: MembershipTeam) -> str:
        if workflow.info().workflow_id != get_membership_workflow_id(input.team_id):
            raise ApplicationError("Use the team membership workflow ID", non_retryable=True)
        self.input = input
        self.run_id = workflow.info().first_execution_run_id
        self.status = input.cursor.status if input.cursor else "starting"
        if input.cursor is None:
            await self.observe("started")
        waiting_since = None
        for _ in range(100):
            if self.cancel_requested:
                break
            try:
                result = await self.process_batch()
                if result.status == "cancelled":
                    break
                if result.status in ("ready", "disabled", "completed"):
                    await self.observe("completed")
                    return result.status
                if result.status == "waiting_for_dictionary":
                    waiting_since = waiting_since or workflow.now()
                    if workflow.now() - waiting_since >= timedelta(minutes=30):
                        raise ApplicationError("Membership dictionary did not refresh")
                    await workflow.wait_condition(lambda: self.cancel_requested, timeout=timedelta(seconds=30))
                else:
                    waiting_since = None
            except TimeoutError:
                continue
            except Exception as error:
                self.status = "failed"
                cause = error.__cause__ or error
                self.error_type = (
                    cause.type if isinstance(cause, ApplicationError) and cause.type else type(cause).__name__
                )
                try:
                    await workflow.execute_activity(
                        fail_membership_backfill_activity,
                        MembershipFailure(
                            team_id=input.team_id,
                            version=self.input.cursor.version if self.input.cursor else self.input.version,
                            error_type=self.error_type,
                            account_keys=input.account_keys,
                            dry_run=input.dry_run,
                        ),
                        start_to_close_timeout=timedelta(minutes=1),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                except ActivityError:
                    workflow.logger.warning("Membership backfill failure update failed")
                await self.observe("failed")
                await workflow.wait_condition(lambda: self.resume_requested or self.cancel_requested)
                self.resume_requested = False
                waiting_since = None
                if not self.cancel_requested:
                    self.status = "resuming"
                    await self.observe("resumed")
        if self.cancel_requested:
            self.status = "cancelled"
            await self.observe("cancelled")
            return self.status
        return workflow.continue_as_new(self.input)


@workflow.defn(name=COORDINATOR_NAME)
class MembershipCoordinatorWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> MembershipCoordinatorInput:
        return MembershipCoordinatorInput(**json.loads(inputs[0])) if inputs else MembershipCoordinatorInput()

    @workflow.run
    async def run(self, input: MembershipCoordinatorInput) -> None:
        after = input.after_team_id
        for _ in range(50):
            page = await workflow.execute_activity(
                sync_membership_page_activity,
                MembershipCoordinatorInput(after_team_id=after, dry_run=input.dry_run),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            for team in page.teams:
                try:
                    await workflow.start_child_workflow(
                        MembershipBackfillWorkflow.run,
                        team,
                        id=get_membership_workflow_id(team.team_id),
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                        parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                except WorkflowAlreadyStartedError:
                    pass
            if page.next_team_id is None:
                return
            after = page.next_team_id
        workflow.continue_as_new(MembershipCoordinatorInput(after_team_id=after, dry_run=input.dry_run))


def create_membership_schedule(state: ScheduleState) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            COORDINATOR_NAME,
            MembershipCoordinatorInput(dry_run=False),
            id=COORDINATOR_NAME,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=timedelta(hours=24),
            retry_policy=RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=timedelta(hours=1), offset=deterministic_offset(SCHEDULE_ID, timedelta(hours=1))
                )
            ]
        ),
        state=state,
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def create_membership_coordinator_schedule(client: Client) -> None:
    if await a_schedule_exists(client, SCHEDULE_ID):
        description = await client.get_schedule_handle(SCHEDULE_ID).describe()
        await a_update_schedule(
            client, SCHEDULE_ID, create_membership_schedule(description.schedule.state), keep_paused=True
        )
    else:
        await a_create_schedule(
            client,
            SCHEDULE_ID,
            create_membership_schedule(ScheduleState(paused=True, note="Enable after live ingestion is ready")),
            trigger_immediately=False,
        )
