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
from temporalio.common import RetryPolicy

from posthog.temporal.ai_observability.eval_reports.constants import (
    CHECK_COUNT_TRIGGERED_REPORTS_WORKFLOW_NAME,
    COORDINATOR_EXECUTION_TIMEOUT,
    COUNT_TRIGGER_SCHEDULE_ID,
    SCHEDULE_ALL_EVAL_REPORTS_WORKFLOW_NAME,
    SCHEDULE_ID,
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
            asdict(
                ScheduleAllEvalReportsWorkflowInputs(
                    region=(settings.CLOUD_DEPLOYMENT or "local").lower(),
                )
            ),
            id=SCHEDULE_ID,
            task_queue=settings.LLMA_TASK_QUEUE,
            execution_timeout=COORDINATOR_EXECUTION_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=timedelta(hours=1),
            pause_on_failure=False,
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
            asdict(
                CheckCountTriggeredReportsWorkflowInputs(
                    region=(settings.CLOUD_DEPLOYMENT or "local").lower(),
                )
            ),
            id=COUNT_TRIGGER_SCHEDULE_ID,
            task_queue=settings.LLMA_TASK_QUEUE,
            execution_timeout=COORDINATOR_EXECUTION_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=5))]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=timedelta(minutes=5),
            pause_on_failure=False,
        ),
    )

    if await a_schedule_exists(client, COUNT_TRIGGER_SCHEDULE_ID):
        await a_update_schedule(client, COUNT_TRIGGER_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, COUNT_TRIGGER_SCHEDULE_ID, schedule, trigger_immediately=False)
