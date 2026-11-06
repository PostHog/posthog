"""Starting eval suggestion workflows. Light on purpose: the API and schedule setup import it, the pipeline stays out."""

from datetime import timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
)
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy

from posthog.dataclasses import frozen
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

COORDINATOR_WORKFLOW_NAME = "llma-eval-suggestions-coordinator"
TEAM_WORKFLOW_NAME = "llma-eval-suggestions-team"
SCHEDULE_ID = "llma-eval-suggestions-coordinator-schedule"
# Runs weekly with overlaps skipped, so it can take most of the week: 2,000 teams of 3 minutes at 4 at a time is 25 hours.
COORDINATOR_TIMEOUT = timedelta(days=6)


@frozen
class ActivityLimits:
    start_to_close: timedelta
    attempts: int
    retry_interval: timedelta = timedelta(seconds=30)
    # Worker queue time an activity may wait before its first attempt starts.
    queue: timedelta = timedelta(minutes=2)

    @property
    def schedule_to_close(self) -> timedelta:
        return self.start_to_close * self.attempts + self.retry_interval * (self.attempts - 1) + self.queue


START_RUN = ActivityLimits(start_to_close=timedelta(minutes=1), attempts=3)
MEASURE = ActivityLimits(start_to_close=timedelta(minutes=10), attempts=2, retry_interval=timedelta(minutes=1))
# Screening and dedupe calls stop at their own budgets, 7 minutes together, before this runs out.
SCREEN = ActivityLimits(start_to_close=timedelta(minutes=9), attempts=2, retry_interval=timedelta(minutes=1))
# One attempt: a retry would pay for the draft again. Room for the slowest draft and measuring it.
DRAFT = ActivityLimits(start_to_close=timedelta(minutes=15), attempts=1)
PUBLISH = ActivityLimits(start_to_close=timedelta(minutes=2), attempts=3)
FAIL_RUN = ActivityLimits(start_to_close=timedelta(minutes=1), attempts=3)
# The activities run one after another, so the workflow needs room for each one's whole schedule-to-close.
TEAM_TIMEOUT = sum(
    (limits.schedule_to_close for limits in (START_RUN, MEASURE, SCREEN, DRAFT, PUBLISH, FAIL_RUN)), timedelta()
)


@frozen
class CoordinatorInputs:
    # Set on continue_as_new legs, so team discovery runs once per week.
    remaining_team_ids: list[int] | None = None
    batch_id: str = ""
    max_concurrent_teams: int = 4


@frozen
class TeamRunInputs:
    team_id: int
    trigger: str
    include_paid: bool
    batch_id: str = ""
    # Set when the caller created the run row first, so the page sees the run before a worker picks it up.
    run_id: str = ""


async def start_first_visit_run(team_id: int, run_id: str) -> None:
    """Start the free stages for one team. A run already in flight for the team absorbs the request."""
    client = await async_connect()
    await client.start_workflow(
        TEAM_WORKFLOW_NAME,
        TeamRunInputs(team_id=team_id, trigger="first_visit", include_paid=False, run_id=run_id),
        id=f"{TEAM_WORKFLOW_NAME}-{team_id}-first-visit",
        task_queue=settings.LLMA_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        execution_timeout=TEAM_TIMEOUT,
        retry_policy=RetryPolicy(maximum_attempts=1),
    )


async def create_eval_suggestions_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            COORDINATOR_WORKFLOW_NAME,
            CoordinatorInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.LLMA_TASK_QUEUE,
            execution_timeout=COORDINATOR_TIMEOUT,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Saturday 01:00 UTC, so cards are ready on Monday",
                    hour=[ScheduleRange(start=1, end=1)],
                    day_of_week=[ScheduleRange(start=6, end=6)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        # An operator's pause holds across deploys.
        await a_update_schedule(client, SCHEDULE_ID, schedule, keep_paused=True)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
