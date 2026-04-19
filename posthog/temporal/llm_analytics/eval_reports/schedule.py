"""Temporal schedule registration for evaluation reports."""

from dataclasses import asdict
from datetime import timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
    ScheduleState,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.llm_analytics.eval_reports.constants import (
    CHECK_COUNT_TRIGGERED_REPORTS_WORKFLOW_NAME,
    COUNT_TRIGGER_SCHEDULE_ID,
    SCHEDULE_ALL_EVAL_REPORTS_WORKFLOW_NAME,
    SCHEDULE_ID,
)
from posthog.temporal.llm_analytics.eval_reports.types import (
    CheckCountTriggeredReportsWorkflowInputs,
    ScheduleAllEvalReportsWorkflowInputs,
)

# Schedules are created paused on initial deploy so operators can verify the
# specs in Temporal UI before they start firing. A follow-up PR will flip these
# to paused=False once the first deploy is verified end-to-end.
_INITIAL_PAUSED = True


async def create_eval_reports_schedule(client: Client):
    """Create or update the hourly schedule for time-based evaluation reports."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SCHEDULE_ALL_EVAL_REPORTS_WORKFLOW_NAME,
            asdict(ScheduleAllEvalReportsWorkflowInputs()),
            id=SCHEDULE_ID,
            task_queue=settings.LLMA_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
        state=ScheduleState(paused=_INITIAL_PAUSED, note="Paused on initial deploy; enable via follow-up PR"),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)


async def create_count_trigger_schedule(client: Client):
    """Create or update the 5-minute schedule for count-based evaluation reports."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            CHECK_COUNT_TRIGGERED_REPORTS_WORKFLOW_NAME,
            asdict(CheckCountTriggeredReportsWorkflowInputs()),
            id=COUNT_TRIGGER_SCHEDULE_ID,
            task_queue=settings.LLMA_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=5))]),
        state=ScheduleState(paused=_INITIAL_PAUSED, note="Paused on initial deploy; enable via follow-up PR"),
    )

    if await a_schedule_exists(client, COUNT_TRIGGER_SCHEDULE_ID):
        await a_update_schedule(client, COUNT_TRIGGER_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, COUNT_TRIGGER_SCHEDULE_ID, schedule, trigger_immediately=False)
