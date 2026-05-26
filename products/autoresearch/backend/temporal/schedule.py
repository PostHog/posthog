"""Temporal schedule for the daily autoresearch coordinator workflow."""

from __future__ import annotations

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

_SCHEDULE_ID = "autoresearch-daily-coordinator"
_WORKFLOW_ID = "autoresearch-coordinator"


async def create_autoresearch_daily_schedule(client: Client) -> None:
    """Create or update the daily schedule for the autoresearch coordinator workflow.

    Fires once per day at 2 AM UTC. The coordinator fans out inference, validation,
    and training-kickoff for every active pipeline. SKIP overlap prevents a new run
    from starting if the previous day's coordinator is still executing.
    """
    from django.conf import settings

    from products.autoresearch.backend.temporal.workflows import CoordinatorWorkflowInput

    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "autoresearch-coordinator",
            CoordinatorWorkflowInput(),
            id=_WORKFLOW_ID,
            task_queue=settings.AUTORESEARCH_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 2 AM UTC",
                    hour=[ScheduleRange(start=2, end=2)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, _SCHEDULE_ID):
        await a_update_schedule(client, _SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, _SCHEDULE_ID, schedule, trigger_immediately=False)
