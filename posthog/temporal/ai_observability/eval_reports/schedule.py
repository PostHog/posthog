"""Temporal schedule registration for evaluation reports."""

from dataclasses import asdict
from datetime import timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.ai_observability.eval_reports.constants import (
    CHECK_COUNT_TRIGGERED_REPORTS_WORKFLOW_NAME,
    COUNT_TRIGGER_POLL_INTERVAL,
    COUNT_TRIGGER_SCHEDULE_ID,
    COUNT_TRIGGERED_COORDINATOR_EXECUTION_TIMEOUT,
    SCHEDULE_ALL_EVAL_REPORTS_WORKFLOW_NAME,
    SCHEDULE_ID,
    SCHEDULED_COORDINATOR_EXECUTION_TIMEOUT,
)
from posthog.temporal.ai_observability.eval_reports.types import (
    CheckCountTriggeredReportsWorkflowInputs,
    ScheduleAllEvalReportsWorkflowInputs,
)
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule


async def create_eval_reports_schedule(client: Client):
    """Create or update the hourly schedule for time-based evaluation reports."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SCHEDULE_ALL_EVAL_REPORTS_WORKFLOW_NAME,
            asdict(ScheduleAllEvalReportsWorkflowInputs()),
            id=SCHEDULE_ID,
            task_queue=settings.LLMA_TASK_QUEUE,
            execution_timeout=SCHEDULED_COORDINATOR_EXECUTION_TIMEOUT,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=timedelta(hours=1),
        ),
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
            execution_timeout=COUNT_TRIGGERED_COORDINATOR_EXECUTION_TIMEOUT,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=COUNT_TRIGGER_POLL_INTERVAL)]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=timedelta(minutes=5),
        ),
    )

    if await a_schedule_exists(client, COUNT_TRIGGER_SCHEDULE_ID):
        await a_update_schedule(client, COUNT_TRIGGER_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, COUNT_TRIGGER_SCHEDULE_ID, schedule, trigger_immediately=False)
