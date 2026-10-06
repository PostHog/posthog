"""Erases Customer analytics membership rows that a durable deletion receipt names.

A paused-by-default coordinator schedule confirms receipts from positive deletion evidence and starts
one independent workflow per confirmed receipt. Workflow payloads carry only team and receipt IDs."""

from __future__ import annotations

import json
from collections.abc import Awaitable
from typing import Literal, TypeVar
from uuid import UUID

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
    WorkflowExecutionStatus,
)
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

with workflow.unsafe.imports_passed_through():
    import threading
    from dataclasses import replace
    from datetime import datetime, timedelta

    from django.conf import settings

    import structlog

    from posthog.dataclasses import frozen
    from posthog.sync import database_sync_to_async_pool
    from posthog.temporal.common.base import PostHogWorkflow
    from posthog.temporal.common.client import async_connect
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

    from products.customer_analytics.backend.facade.membership_deletion_contracts import (
        MembershipDeletionCursor,
        MembershipDeletionInput,
    )
    from products.customer_analytics.backend.logic import membership_deletion_receipts as receipts
    from products.customer_analytics.backend.logic.membership_deletion import (
        discover_team_deletions,
        membership_cluster,
        process_membership_deletion,
        recover_prepared_deletions,
    )

LOGGER = structlog.get_logger(__name__)
T = TypeVar("T")

MEMBERSHIP_DELETION_WORKFLOW_NAME = "customer-analytics-membership-deletion"
MEMBERSHIP_DELETION_COORDINATOR_WORKFLOW_NAME = "customer-analytics-membership-deletion-coordinator"
MEMBERSHIP_DELETION_COORDINATOR_SCHEDULE_ID = "customer-analytics-membership-deletion-coordinator-schedule"
MEMBERSHIP_DELETION_INTERVAL = timedelta(minutes=15)
# Continue-as-new keeps each coordinator run's history small while one tick still scans every pending receipt.
MAX_ACTIVITIES_PER_RUN = 40
MAX_STARTS_PER_TICK = 100
MAX_RUNNING_RECEIPTS = 4
MAX_TICK_DURATION = timedelta(minutes=10)
# A receipt workflow stays open through its retries, so the coordinator skips it instead of restarting it.
MEMBERSHIP_DELETION_EXECUTION_TIMEOUT = timedelta(minutes=30)
COORDINATOR_EXECUTION_TIMEOUT = timedelta(hours=1)
NON_RETRYABLE_ERRORS = ("LookupError",)
_SCAN_TIMEOUT = timedelta(minutes=5)
_SCAN_RETRY = RetryPolicy(maximum_attempts=3)


@frozen
class MembershipDeletionCoordinatorInput:
    stage: Literal["discover", "recover", "dispatch"] = "discover"
    discovery_after: int = 0
    recovery_after: MembershipDeletionCursor | None = None
    dispatch_after: MembershipDeletionCursor | None = None
    started: int = 0
    tick_started_at: datetime | None = None


@frozen
class MembershipDeletionDiscoveryInput:
    after_id: int


@frozen
class MembershipDeletionRecoveryInput:
    after: MembershipDeletionCursor | None


@frozen
class MembershipDeletionDispatchInput:
    after: MembershipDeletionCursor | None
    limit: int


@frozen
class MembershipDeletionDispatch:
    started: int
    next_cursor: MembershipDeletionCursor | None
    busy: bool = False


def membership_deletion_workflow_id(receipt_id: UUID) -> str:
    return f"{MEMBERSHIP_DELETION_WORKFLOW_NAME}-{receipt_id}"


async def _sanitized(call: Awaitable[T]) -> T:
    try:
        return await call
    except Exception as error:
        failure = ApplicationError(
            f"Membership deletion failed with {type(error).__name__}",
            type=type(error).__name__,
            non_retryable=type(error).__name__ in NON_RETRYABLE_ERRORS,
        )
    # Raised outside the handler so messages that can echo distinct IDs never reach Temporal or logs.
    raise failure


@activity.defn
async def membership_deletion_cleanup_activity(input: MembershipDeletionInput) -> None:
    details = activity.info().heartbeat_details
    after_id = int(details[0]) if details else 0
    stop = threading.Event()
    heartbeater = Heartbeater(details=(after_id,))
    async with heartbeater:

        def on_page(cursor: int) -> None:
            heartbeater.details = (cursor,)

        def run() -> None:
            details = receipts.get_membership_deletion(input.team_id, input.receipt_id)
            if details.completed:
                return
            if not receipts.claim_membership_deletion(
                input.team_id, input.receipt_id, max_running=MAX_RUNNING_RECEIPTS
            ):
                raise RuntimeError("Membership deletion capacity is unavailable")
            process_membership_deletion(
                membership_cluster(),
                input.team_id,
                input.receipt_id,
                after_id=after_id,
                on_page=on_page,
                should_stop=stop.is_set,
            )

        try:
            await _sanitized(database_sync_to_async_pool(run)())
        finally:
            # A timed-out attempt leaves its thread running, so the flag ends it after the page in flight.
            stop.set()


@activity.defn
async def membership_deletion_discover_teams_activity(input: MembershipDeletionDiscoveryInput) -> int | None:
    return await _sanitized(database_sync_to_async_pool(discover_team_deletions)(input.after_id))


@activity.defn
async def membership_deletion_recover_activity(
    input: MembershipDeletionRecoveryInput,
) -> MembershipDeletionCursor | None:
    return await _sanitized(database_sync_to_async_pool(recover_prepared_deletions)(input.after))


async def _release_closed_claims(client: Client) -> None:
    claimed = await database_sync_to_async_pool(receipts.list_claimed_membership_deletions)()
    for reference in claimed:
        try:
            description = await client.get_workflow_handle(membership_deletion_workflow_id(reference.id)).describe()
        except RPCError as error:
            if error.status != RPCStatusCode.NOT_FOUND:
                continue
        except Exception:
            continue
        else:
            if description.status == WorkflowExecutionStatus.RUNNING:
                continue
        await database_sync_to_async_pool(receipts.release_membership_deletion_claim)(reference.team_id, reference.id)


@activity.defn
async def membership_deletion_dispatch_activity(input: MembershipDeletionDispatchInput) -> MembershipDeletionDispatch:
    client = await async_connect()
    await _sanitized(_release_closed_claims(client))
    page = await _sanitized(database_sync_to_async_pool(receipts.list_pending_membership_deletions)(input.after))
    started = 0
    for reference in page.receipts:
        if started >= input.limit:
            return MembershipDeletionDispatch(started=started, next_cursor=None)
        claimed = await _sanitized(
            database_sync_to_async_pool(receipts.claim_membership_deletion)(
                reference.team_id, reference.id, max_running=MAX_RUNNING_RECEIPTS
            )
        )
        if not claimed:
            return MembershipDeletionDispatch(started=started, next_cursor=None, busy=True)
        try:
            await client.start_workflow(
                MEMBERSHIP_DELETION_WORKFLOW_NAME,
                MembershipDeletionInput(team_id=reference.team_id, receipt_id=reference.id),
                id=membership_deletion_workflow_id(reference.id),
                task_queue=activity.info().task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                execution_timeout=MEMBERSHIP_DELETION_EXECUTION_TIMEOUT,
            )
            started += 1
        except WorkflowAlreadyStartedError:
            continue
        except Exception as error:
            LOGGER.warning(
                "membership_deletion_start_failed", receipt_id=str(reference.id), error_type=type(error).__name__
            )
    return MembershipDeletionDispatch(started=started, next_cursor=page.next_cursor)


@workflow.defn(name=MEMBERSHIP_DELETION_WORKFLOW_NAME)
class MembershipDeletionWorkflow(PostHogWorkflow):
    @classmethod
    def parse_inputs(cls, inputs: list[str]) -> MembershipDeletionInput:
        loaded = json.loads(inputs[0])
        return MembershipDeletionInput(team_id=int(loaded["team_id"]), receipt_id=UUID(loaded["receipt_id"]))

    @workflow.run
    async def run(self, input: MembershipDeletionInput) -> None:
        await workflow.execute_activity(
            membership_deletion_cleanup_activity,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=30),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(minutes=2),
                maximum_attempts=3,
                non_retryable_error_types=list(NON_RETRYABLE_ERRORS),
            ),
        )


@workflow.defn(name=MEMBERSHIP_DELETION_COORDINATOR_WORKFLOW_NAME)
class MembershipDeletionCoordinatorWorkflow(PostHogWorkflow):
    @classmethod
    def parse_inputs(cls, inputs: list[str]) -> MembershipDeletionCoordinatorInput:
        return MembershipDeletionCoordinatorInput()

    @workflow.run
    async def run(self, input: MembershipDeletionCoordinatorInput) -> None:
        state = input if input.tick_started_at is not None else replace(input, tick_started_at=workflow.now())
        for _ in range(MAX_ACTIVITIES_PER_RUN):
            if state.tick_started_at is not None and workflow.now() - state.tick_started_at >= MAX_TICK_DURATION:
                return
            if state.stage == "discover":
                try:
                    after_id = await workflow.execute_activity(
                        membership_deletion_discover_teams_activity,
                        MembershipDeletionDiscoveryInput(after_id=state.discovery_after),
                        start_to_close_timeout=_SCAN_TIMEOUT,
                        retry_policy=_SCAN_RETRY,
                    )
                except ActivityError:
                    after_id = None
                if after_id is None:
                    state = replace(state, stage="recover")
                else:
                    state = replace(state, discovery_after=after_id)
            elif state.stage == "recover":
                try:
                    cursor = await workflow.execute_activity(
                        membership_deletion_recover_activity,
                        MembershipDeletionRecoveryInput(after=state.recovery_after),
                        start_to_close_timeout=_SCAN_TIMEOUT,
                        retry_policy=_SCAN_RETRY,
                    )
                except ActivityError:
                    cursor = None
                if cursor is None:
                    state = replace(state, stage="dispatch")
                else:
                    state = replace(state, recovery_after=cursor)
            else:
                dispatch = await workflow.execute_activity(
                    membership_deletion_dispatch_activity,
                    MembershipDeletionDispatchInput(
                        after=state.dispatch_after, limit=MAX_STARTS_PER_TICK - state.started
                    ),
                    start_to_close_timeout=_SCAN_TIMEOUT,
                    retry_policy=_SCAN_RETRY,
                )
                started = state.started + dispatch.started
                if started >= MAX_STARTS_PER_TICK:
                    return
                if dispatch.busy:
                    await workflow.sleep(timedelta(seconds=10))
                    state = replace(state, dispatch_after=None, started=started)
                elif dispatch.next_cursor is None:
                    return
                else:
                    state = replace(state, dispatch_after=dispatch.next_cursor, started=started)
        workflow.continue_as_new(state)


def _build_coordinator_schedule(state: ScheduleState) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            MEMBERSHIP_DELETION_COORDINATOR_WORKFLOW_NAME,
            MembershipDeletionCoordinatorInput(),
            id=MEMBERSHIP_DELETION_COORDINATOR_WORKFLOW_NAME,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=COORDINATOR_EXECUTION_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=MEMBERSHIP_DELETION_INTERVAL, offset=timedelta(minutes=3))]
        ),
        state=state,
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def create_membership_deletion_coordinator_schedule(client: Client) -> None:
    if await a_schedule_exists(client, MEMBERSHIP_DELETION_COORDINATOR_SCHEDULE_ID):
        # Every worker start runs this, so an operator's pause or unpause must survive it.
        description = await client.get_schedule_handle(MEMBERSHIP_DELETION_COORDINATOR_SCHEDULE_ID).describe()
        schedule = _build_coordinator_schedule(description.schedule.state)
        await a_update_schedule(client, MEMBERSHIP_DELETION_COORDINATOR_SCHEDULE_ID, schedule)
        return
    paused = ScheduleState(paused=True, note="Membership deletion cleanup starts paused until an operator enables it")
    await a_create_schedule(
        client,
        MEMBERSHIP_DELETION_COORDINATOR_SCHEDULE_ID,
        _build_coordinator_schedule(paused),
        trigger_immediately=False,
    )
