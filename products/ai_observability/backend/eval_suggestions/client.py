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
COORDINATOR_TIMEOUT = timedelta(hours=20)
# Room for the start, two 15-minute execute attempts a minute apart, and the cleanup that marks a run failed.
TEAM_TIMEOUT = timedelta(minutes=45)


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


async def start_first_visit_run(team_id: int) -> None:
    """Start the free stages for one team. A run already in flight for the team absorbs the request."""
    client = await async_connect()
    await client.start_workflow(
        TEAM_WORKFLOW_NAME,
        TeamRunInputs(team_id=team_id, trigger="first_visit", include_paid=False),
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
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
