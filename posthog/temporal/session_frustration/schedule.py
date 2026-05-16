"""Schedule configuration for hourly session frustration detection."""

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
from posthog.temporal.session_frustration.constants import LOOKBACK_WINDOW, SCHEDULE_INTERVAL
from posthog.temporal.session_frustration.types import CoordinatorInputs

SCHEDULE_ID = "session-frustration-detection-schedule"


async def create_session_frustration_detection_schedule(client: Client):
    """Run frustration detection on schedule.

    Every hour, discover teams with frustration detection enabled and scan
    their completed sessions for frustration signals (rage clicks, exceptions).
    Emit $session_frustration_detected events for sessions above the threshold.
    """
    coordinator_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "session-frustration-detection-coordinator",
            CoordinatorInputs(
                lookback_hours=int(LOOKBACK_WINDOW.total_seconds() / 3600),
            ),
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=SCHEDULE_INTERVAL,
        ),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, coordinator_schedule)
    else:
        await a_create_schedule(
            client,
            SCHEDULE_ID,
            coordinator_schedule,
            trigger_immediately=False,
        )
