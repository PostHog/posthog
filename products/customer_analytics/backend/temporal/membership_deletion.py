"""Payloads, results and heartbeats carry only cursors, counts and a bounded list of team IDs, never
distinct IDs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

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
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    import time
    import threading
    from dataclasses import field, replace
    from datetime import datetime, timedelta

    from django.conf import settings

    from posthog.dataclasses import frozen
    from posthog.sync import database_sync_to_async_pool
    from posthog.temporal.common.base import PostHogWorkflow
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

    from products.customer_analytics.backend.logic.membership_deletion import membership_cluster
    from products.customer_analytics.backend.logic.membership_deletion_consumer import (
        TeamScanOutcome,
        TombstonePageOutcome,
        TombstoneResume,
        process_tombstone_page,
        reconcile_deleted_teams,
    )

T = TypeVar("T")

MEMBERSHIP_DELETION_COORDINATOR_WORKFLOW_NAME = "customer-analytics-membership-deletion-coordinator"
MEMBERSHIP_DELETION_COORDINATOR_SCHEDULE_ID = "customer-analytics-membership-deletion-coordinator-schedule"
MEMBERSHIP_DELETION_INTERVAL = timedelta(minutes=15)
# Continue-as-new keeps each run's history small while one tick still pages through the whole log.
MAX_ACTIVITIES_PER_RUN = 40
MAX_TICK_DURATION = timedelta(minutes=10)
COORDINATOR_EXECUTION_TIMEOUT = timedelta(hours=1)
_PAGE_TIMEOUT = timedelta(minutes=10)
# Activities stop on their own at this budget and return where they stopped. The rest of the timeout
# leaves room for the chunk in flight, which can wait for mutation capacity.
_PAGE_BUDGET = timedelta(minutes=6)
_PAGE_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
# The log cursor carries over to the next run, so a backlog spreads over runs instead of each run rereading it.
MAX_TOMBSTONE_PAGES_PER_RUN = 30
MAX_SKIPPED_TEAMS = 100
_PAGE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)


@frozen
class MembershipDeletionProgress:
    tombstone_after: int | None = None
    resume: TombstoneResume | None = None
    team_after: int = 0
    # Teams that failed during the current pass. Their entries stay pending, and the rest of the pass skips
    # them so that later teams get processed. The next pass retries them.
    skipped_team_ids: tuple[int, ...] = ()


@frozen
class MembershipDeletionCoordinatorInput:
    progress: MembershipDeletionProgress = field(default_factory=MembershipDeletionProgress)
    stage: Literal["first_team_page", "tombstones", "teams", "done"] = "first_team_page"
    tombstone_pages: int = 0
    team_scan_finished: bool = False
    tick_started_at: datetime | None = None


@frozen
class MembershipTombstonePageInput:
    after: int | None
    resume: TombstoneResume | None = None
    skip_team_ids: tuple[int, ...] = ()


@frozen
class MembershipTeamScanInput:
    after: int


async def _sanitized(call: Awaitable[T]) -> T:
    try:
        return await call
    except Exception as error:
        failure = ApplicationError(f"Membership deletion failed with {type(error).__name__}", type=type(error).__name__)
    # Raised outside the handler so messages that can echo distinct IDs never reach Temporal or logs.
    raise failure


async def _run_in_thread(
    fn: Callable[[Callable[[], bool], Heartbeater], T], heartbeat_details: tuple[int, ...] = ()
) -> T:
    stop = threading.Event()
    deadline = time.monotonic() + _PAGE_BUDGET.total_seconds()

    def should_stop() -> bool:
        return stop.is_set() or time.monotonic() >= deadline

    # Every heartbeat replaces the recorded details, so an attempt starts by repeating the cursor it resumes
    # from. Otherwise its first heartbeat would erase that cursor before it verifies anything new.
    heartbeater = Heartbeater(details=heartbeat_details)
    async with heartbeater:
        try:
            return await _sanitized(database_sync_to_async_pool(fn)(should_stop, heartbeater))
        finally:
            # A timed-out attempt leaves its thread running, so the flag ends it at the next check.
            stop.set()


def _heartbeat_resume() -> TombstoneResume | None:
    details = activity.info().heartbeat_details
    if len(details) != 3:
        return None
    team_id, log_id, after_id = (int(value) for value in details)
    return TombstoneResume(team_id=team_id, log_id=log_id, after_id=after_id)


@activity.defn
async def membership_deletion_tombstone_page_activity(input: MembershipTombstonePageInput) -> TombstonePageOutcome:
    resume = _heartbeat_resume() or input.resume

    def run(should_stop: Callable[[], bool], heartbeater: Heartbeater) -> TombstonePageOutcome:
        def on_progress(progress: TombstoneResume) -> None:
            heartbeater.details = (progress.team_id, progress.log_id, progress.after_id)

        return process_tombstone_page(
            membership_cluster(),
            after=input.after,
            resume=resume,
            skip_team_ids=frozenset(input.skip_team_ids),
            should_stop=should_stop,
            on_progress=on_progress,
        )

    details = (resume.team_id, resume.log_id, resume.after_id) if resume is not None else ()
    return await _run_in_thread(run, details)


@activity.defn
async def membership_deletion_team_scan_activity(input: MembershipTeamScanInput) -> TeamScanOutcome:
    return await _run_in_thread(
        lambda should_stop, _heartbeater: reconcile_deleted_teams(
            membership_cluster(), after=input.after, should_stop=should_stop
        )
    )


def progress_from_completion_result(value: object) -> MembershipDeletionProgress:
    """An unknown shape starts a new pass instead of failing the run."""
    if not isinstance(value, dict):
        return MembershipDeletionProgress()
    # An older result was the bare resume position.
    resume_value = value if "log_id" in value else value.get("resume")
    try:
        resume = (
            TombstoneResume(
                team_id=int(resume_value["team_id"]),
                log_id=int(resume_value["log_id"]),
                after_id=int(resume_value["after_id"]),
            )
            if isinstance(resume_value, dict)
            else None
        )
        after = value.get("tombstone_after")
        skipped = value.get("skipped_team_ids") or ()
        return MembershipDeletionProgress(
            tombstone_after=int(after) if after is not None else None,
            resume=resume,
            team_after=int(value.get("team_after") or 0),
            skipped_team_ids=tuple(int(team_id) for team_id in list(skipped)[-MAX_SKIPPED_TEAMS:]),
        )
    except (KeyError, TypeError, ValueError):
        return MembershipDeletionProgress()


def _skip(skipped: tuple[int, ...], failed: tuple[int, ...]) -> tuple[int, ...]:
    # Past the cap, the oldest entries drop out. Those teams are only retried, never lost.
    merged = skipped + tuple(team_id for team_id in dict.fromkeys(failed) if team_id not in skipped)
    return merged[-MAX_SKIPPED_TEAMS:]


@workflow.defn(name=MEMBERSHIP_DELETION_COORDINATOR_WORKFLOW_NAME)
class MembershipDeletionCoordinatorWorkflow(PostHogWorkflow):
    @classmethod
    def parse_inputs(cls, inputs: list[str]) -> MembershipDeletionCoordinatorInput:
        return MembershipDeletionCoordinatorInput()

    @workflow.run
    async def run(self, input: MembershipDeletionCoordinatorInput) -> MembershipDeletionProgress:
        state = input
        if state.tick_started_at is None:
            # A schedule gives each run the result of the last completed run, which carries the cursors.
            if workflow.has_last_completion_result():
                state = replace(state, progress=progress_from_completion_result(workflow.get_last_completion_result()))
            state = replace(state, tick_started_at=workflow.now())
        for _ in range(MAX_ACTIVITIES_PER_RUN):
            if state.tick_started_at is not None and workflow.now() - state.tick_started_at >= MAX_TICK_DURATION:
                return state.progress
            if state.stage == "tombstones":
                if state.tombstone_pages >= MAX_TOMBSTONE_PAGES_PER_RUN:
                    return state.progress
                state = await self._tombstone_page(state)
            else:
                state = await self._team_page(state)
            if state.stage == "done":
                return state.progress
        workflow.continue_as_new(state)

    async def _tombstone_page(self, state: MembershipDeletionCoordinatorInput) -> MembershipDeletionCoordinatorInput:
        progress = state.progress
        try:
            page = await workflow.execute_activity(
                membership_deletion_tombstone_page_activity,
                MembershipTombstonePageInput(
                    after=progress.tombstone_after, resume=progress.resume, skip_team_ids=progress.skipped_team_ids
                ),
                start_to_close_timeout=_PAGE_TIMEOUT,
                heartbeat_timeout=_PAGE_HEARTBEAT_TIMEOUT,
                retry_policy=_PAGE_RETRY,
            )
        except ActivityError:
            # The entries and the cursor stay, so the next run reads this page again.
            return replace(state, stage="done")
        if page.failed_team_ids:
            workflow.logger.warning(
                "Membership tombstone page left teams pending", extra={"failed_teams": len(page.failed_team_ids)}
            )
        pages = state.tombstone_pages + 1
        if page.resume is None and page.next_cursor is None:
            # End of the log: the next pass starts at the first pending entry and retries the skipped teams.
            stage: Literal["teams", "done"] = "done" if state.team_scan_finished else "teams"
            return replace(
                state,
                progress=MembershipDeletionProgress(team_after=progress.team_after),
                stage=stage,
                tombstone_pages=pages,
            )
        return replace(
            state,
            progress=replace(
                progress,
                tombstone_after=page.next_cursor,
                resume=page.resume,
                skipped_team_ids=_skip(progress.skipped_team_ids, page.failed_team_ids),
            ),
            tombstone_pages=pages,
        )

    async def _team_page(self, state: MembershipDeletionCoordinatorInput) -> MembershipDeletionCoordinatorInput:
        first = state.stage == "first_team_page"
        try:
            scan = await workflow.execute_activity(
                membership_deletion_team_scan_activity,
                MembershipTeamScanInput(after=state.progress.team_after),
                start_to_close_timeout=_PAGE_TIMEOUT,
                heartbeat_timeout=_PAGE_HEARTBEAT_TIMEOUT,
                retry_policy=_PAGE_RETRY,
            )
        except ActivityError:
            return replace(state, stage="tombstones" if first else "done")
        if scan.failed_teams or scan.unconfirmed_teams:
            workflow.logger.warning(
                "Membership team scan left teams pending",
                extra={"failed_teams": scan.failed_teams, "unconfirmed_teams": scan.unconfirmed_teams},
            )
        finished = scan.next_cursor is None
        return replace(
            state,
            progress=replace(state.progress, team_after=scan.next_cursor or 0),
            stage="tombstones" if first else ("done" if finished else "teams"),
            team_scan_finished=state.team_scan_finished or finished,
        )


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
