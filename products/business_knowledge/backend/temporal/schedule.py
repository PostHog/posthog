"""Schedule configuration for the hourly business_knowledge refresh coordinator."""

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

SCHEDULE_ID = "business-knowledge-refresh-coordinator-schedule"
SCHEDULE_INTERVAL = timedelta(hours=1)


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
