"""Temporal schedule for the daily autoresearch coordinator workflow."""

from __future__ import annotations

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

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.autoresearch.backend.temporal.workflows import COORDINATOR_TIMEOUT, CoordinatorWorkflowInput

_SCHEDULE_ID = "autoresearch-daily-coordinator"
_WORKFLOW_ID = "autoresearch-coordinator"
_CATCH_UP_SCHEDULE_ID = "autoresearch-catch-up-coordinator"
_CATCH_UP_WORKFLOW_ID = "autoresearch-coordinator-catch-up"
# An inference child can fail up to INFERENCE_WORKFLOW_TIMEOUT after it starts, and the daily sweep starts
# children until its own timeout. Each tick retries the runs lost since the tick before it.
_CATCH_UP_HOURS = [8, 14, 20]


def _coordinator_schedule(
    *, workflow_id: str, inp: CoordinatorWorkflowInput, hours: list[int], comment: str
) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "autoresearch-coordinator",
            inp,
            id=workflow_id,
            task_queue=settings.AUTORESEARCH_TASK_QUEUE,
            execution_timeout=COORDINATOR_TIMEOUT,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(comment=comment, hour=[ScheduleRange(start=hour, end=hour) for hour in hours])
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def _create_or_update(client: Client, schedule_id: str, schedule: Schedule) -> None:
    if await a_schedule_exists(client, schedule_id):
        # Keep the live state, so a deploy does not resume a schedule an operator paused to stop spend.
        description = await client.get_schedule_handle(schedule_id).describe()
        schedule.state = description.schedule.state
        await a_update_schedule(client, schedule_id, schedule)
    else:
        await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)


async def create_autoresearch_daily_schedule(client: Client) -> None:
    """Create or update the two daily schedules for the autoresearch coordinator workflow.

    The daily sweep fires at 2 AM UTC. The coordinator fans out inference, validation,
    and training-kickoff for every active pipeline. SKIP overlap prevents a new run
    from starting if the previous day's coordinator is still executing.

    The catch-up sweep fires at 8 AM, 2 PM and 8 PM UTC. Each tick scores again only the pipelines
    whose latest scheduled run of the day was lost, so a child that times out after one tick gets
    the next. It has its own workflow id, so it can run while the daily sweep is still working
    through its backlog.
    """
    await _create_or_update(
        client,
        _SCHEDULE_ID,
        _coordinator_schedule(
            workflow_id=_WORKFLOW_ID, inp=CoordinatorWorkflowInput(), hours=[2], comment="Daily at 2 AM UTC"
        ),
    )
    await _create_or_update(
        client,
        _CATCH_UP_SCHEDULE_ID,
        _coordinator_schedule(
            workflow_id=_CATCH_UP_WORKFLOW_ID,
            inp=CoordinatorWorkflowInput(catch_up=True),
            hours=_CATCH_UP_HOURS,
            comment="Catch-up at 8 AM, 2 PM and 8 PM UTC",
        ),
    )
