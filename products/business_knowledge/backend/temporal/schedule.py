"""Schedule configuration for Business knowledge coordinators."""

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

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from .learning.constants import LEARNING_COORDINATOR_INTERVAL_MINUTES
from .learning.schemas import LearningCoordinatorInput

SCHEDULE_ID = "business-knowledge-refresh-coordinator-schedule"
SCHEDULE_INTERVAL = timedelta(hours=1)
LEARNING_SCHEDULE_ID = "business-knowledge-learning-coordinator-schedule"
LEARNING_WORKFLOW_NAME = "business-knowledge-learning-coordinator"


async def create_business_knowledge_refresh_coordinator_schedule(client: Client) -> None:
    """Create or update the single global coordinator schedule (idempotent)."""
    coordinator_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "business-knowledge-refresh-coordinator",
            id=SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)]),
        # SKIP plus the per-team advisory lock prevents concurrent double-refresh.
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=SCHEDULE_INTERVAL,
        ),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, coordinator_schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, coordinator_schedule, trigger_immediately=False)


async def create_business_knowledge_learning_coordinator_schedule(client: Client) -> None:
    interval = timedelta(minutes=LEARNING_COORDINATOR_INTERVAL_MINUTES)
    learning_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            LEARNING_WORKFLOW_NAME,
            asdict(LearningCoordinatorInput()),
            id=LEARNING_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=interval)]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=interval,
        ),
    )
    if await a_schedule_exists(client, LEARNING_SCHEDULE_ID):
        await a_update_schedule(client, LEARNING_SCHEDULE_ID, learning_schedule)
    else:
        await a_create_schedule(client, LEARNING_SCHEDULE_ID, learning_schedule, trigger_immediately=False)
