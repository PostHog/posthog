"""Scheduled delivery of Salesforce Task decisions into account ownership: a coordinator on a
Temporal schedule starts one sweep child workflow per project with claims on. The decision contract
and the sweep itself are documented in ``logic/ownership_claims.py``."""

from __future__ import annotations

import json

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
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    import threading
    from collections.abc import Callable
    from datetime import timedelta

    from django.conf import settings

    from posthog.dataclasses import frozen
    from posthog.models.scoping import team_scope
    from posthog.models.team import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

    from products.customer_analytics.backend.logic.ownership_claims import (
        ClaimReconciliation,
        list_ownership_claim_team_ids,
        reconcile_ownership_claims,
    )

OWNERSHIP_CLAIMS_COORDINATOR_WORKFLOW_NAME = "customer-analytics-ownership-claims-coordinator"
OWNERSHIP_CLAIMS_COORDINATOR_SCHEDULE_ID = "customer-analytics-ownership-claims-coordinator-schedule"
OWNERSHIP_CLAIMS_SWEEP_WORKFLOW_NAME = "customer-analytics-ownership-claims-sweep"
# Every sweep reads each bound view to the end, so the cadence trades delivery latency against
# repeated reads of views that have not changed since the last tick.
OWNERSHIP_CLAIMS_INTERVAL = timedelta(minutes=15)
# The coordinator abandons its children, so its own budget is the collect activity's three attempts
# of two minutes plus queue wait. It must stay under the interval: an exception that is not a
# FailureError fails the workflow task, which the server retries without limit, and the SKIP policy
# then drops every later tick for as long as that run stays open.
OWNERSHIP_CLAIMS_COORDINATOR_EXECUTION_TIMEOUT = timedelta(minutes=10)
# A sweep holds its project's fixed child id until it closes, and every later tick skips a project
# whose child is still open. The activity's own timeouts bound a sweep that runs, so this bound is
# only for one that never runs: no worker polls its task, or the task fails on every attempt. It
# stays far above the interval on purpose, because a bound near the activity's would also end a
# sweep that is merely waiting behind other products on the shared queue.
OWNERSHIP_CLAIMS_SWEEP_EXECUTION_TIMEOUT = timedelta(hours=24)


@frozen
class OwnershipClaimsCoordinatorInput:
    pass


@frozen
class OwnershipClaimsSweepInput:
    team_id: int


@frozen
class OwnershipClaimsProjects:
    team_ids: tuple[int, ...]


@frozen
class OwnershipClaimsCoordinatorOutput:
    enabled_teams: int
    started_children: int
    overlapping_children: int


def ownership_claims_workflow_id(team_id: int) -> str:
    return f"customer-analytics-ownership-claims-{team_id}"


@activity.defn
async def ownership_claims_collect_teams_activity(_input: OwnershipClaimsCoordinatorInput) -> OwnershipClaimsProjects:
    team_ids = await database_sync_to_async(list_ownership_claim_team_ids, thread_sensitive=False)()
    return OwnershipClaimsProjects(team_ids=tuple(team_ids))


def _sweep(input: OwnershipClaimsSweepInput, should_stop: Callable[[], bool]) -> ClaimReconciliation:
    try:
        team = Team.objects.get(id=input.team_id)
        with team_scope(team.id):
            return reconcile_ownership_claims(team, should_stop=should_stop)
    except Team.DoesNotExist as error:
        # A deleted project does not heal by retrying; the next tick lists the projects again.
        raise ApplicationError(str(error), non_retryable=True) from error


@activity.defn
async def ownership_claims_sweep_activity(input: OwnershipClaimsSweepInput) -> ClaimReconciliation:
    stop = threading.Event()
    async with Heartbeater():
        try:
            return await database_sync_to_async(_sweep, thread_sensitive=False)(input, stop.is_set)
        finally:
            # A timed-out or cancelled activity leaves its thread running. The flag makes the thread
            # stop between two pages or two decisions, so at most the one decision already in flight
            # can still commit beside the sweep the next tick starts; the tick after that repairs it.
            stop.set()


@workflow.defn(name=OWNERSHIP_CLAIMS_SWEEP_WORKFLOW_NAME)
class OwnershipClaimsSweepWorkflow:
    """One project's sweep. Decision rows never cross the activity boundary; only the outcome
    counts return. Start it through the coordinator only: a direct start under another workflow id
    can run beside the sweep already running for the project."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> OwnershipClaimsSweepInput:
        return OwnershipClaimsSweepInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, input: OwnershipClaimsSweepInput) -> ClaimReconciliation:
        # A retried attempt could run beside the thread of an attempt that timed out, and an older
        # read can apply a claim a newer read has already seen released. The next tick is the retry.
        return await workflow.execute_activity(
            ownership_claims_sweep_activity,
            input,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn(name=OWNERSHIP_CLAIMS_COORDINATOR_WORKFLOW_NAME)
class OwnershipClaimsCoordinatorWorkflow:
    """Starts one sweep child per project with claims on. Child ids are fixed per project, so a
    sweep still running at the next tick is left alone rather than started twice: an older read
    could otherwise apply a claim that a newer read has already seen released. ALLOW_DUPLICATE lets
    the next tick start a fresh sweep once the previous one has closed."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> OwnershipClaimsCoordinatorInput:
        if not inputs:
            return OwnershipClaimsCoordinatorInput()
        return OwnershipClaimsCoordinatorInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, input: OwnershipClaimsCoordinatorInput) -> OwnershipClaimsCoordinatorOutput:
        projects = await workflow.execute_activity(
            ownership_claims_collect_teams_activity,
            input,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        started = 0
        overlapping = 0
        for team_id in projects.team_ids:
            try:
                await workflow.start_child_workflow(
                    OwnershipClaimsSweepWorkflow.run,
                    OwnershipClaimsSweepInput(team_id=team_id),
                    id=ownership_claims_workflow_id(team_id),
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=OWNERSHIP_CLAIMS_SWEEP_EXECUTION_TIMEOUT,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                overlapping += 1
        return OwnershipClaimsCoordinatorOutput(
            enabled_teams=len(projects.team_ids), started_children=started, overlapping_children=overlapping
        )


def _build_ownership_claims_coordinator_schedule(state: ScheduleState) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            OWNERSHIP_CLAIMS_COORDINATOR_WORKFLOW_NAME,
            OwnershipClaimsCoordinatorInput(),
            id=OWNERSHIP_CLAIMS_COORDINATOR_WORKFLOW_NAME,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=OWNERSHIP_CLAIMS_COORDINATOR_EXECUTION_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=OWNERSHIP_CLAIMS_INTERVAL)]),
        state=state,
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def create_ownership_claims_coordinator_schedule(client: Client) -> None:
    if await a_schedule_exists(client, OWNERSHIP_CLAIMS_COORDINATOR_SCHEDULE_ID):
        # Every worker start runs this update, so it must carry an operator's pause rather than
        # replace it with the default running state.
        description = await client.get_schedule_handle(OWNERSHIP_CLAIMS_COORDINATOR_SCHEDULE_ID).describe()
        schedule = _build_ownership_claims_coordinator_schedule(description.schedule.state)
        await a_update_schedule(client, OWNERSHIP_CLAIMS_COORDINATOR_SCHEDULE_ID, schedule)
        return

    schedule = _build_ownership_claims_coordinator_schedule(ScheduleState())
    await a_create_schedule(client, OWNERSHIP_CLAIMS_COORDINATOR_SCHEDULE_ID, schedule, trigger_immediately=False)
