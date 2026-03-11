"""Temporal schedule registration for evaluation reports."""

from dataclasses import asdict
from datetime import timedelta

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.llm_analytics.eval_reports.constants import SCHEDULE_ALL_EVAL_REPORTS_WORKFLOW_NAME, SCHEDULE_ID
from posthog.temporal.llm_analytics.eval_reports.types import ScheduleAllEvalReportsWorkflowInputs


async def create_eval_reports_schedule(client: Client):
    """Create or update the hourly schedule for evaluation report generation."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SCHEDULE_ALL_EVAL_REPORTS_WORKFLOW_NAME,
            asdict(ScheduleAllEvalReportsWorkflowInputs()),
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
