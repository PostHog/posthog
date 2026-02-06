"""Schedule configuration for hourly video segment clustering coordinator."""

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

from posthog.temporal.ai.video_segment_clustering.constants import (
    DEFAULT_LOOKBACK_WINDOW,
    PROACTIVE_TASKS_SCHEDULE_INTERVAL,
)
from posthog.temporal.ai.video_segment_clustering.coordinator_workflow import VideoSegmentClusteringCoordinatorInputs
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule


async def create_video_segment_clustering_coordinator_schedule(client: Client):
    """Run task inference on schedule.

    Every PROACTIVE_TASKS_SCHEDULE_INTERVAL, we run video segment clustering for teams with proactive tasks enabled,
    with a lookback window of DEFAULT_LOOKBACK_WINDOW.
    """
    coordinator_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "video-segment-clustering-coordinator",
            VideoSegmentClusteringCoordinatorInputs(
                lookback_hours=int(DEFAULT_LOOKBACK_WINDOW.total_seconds() / 3600),
            ),
            id="video-segment-clustering-coordinator-schedule",
            task_queue=settings.MAX_AI_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=PROACTIVE_TASKS_SCHEDULE_INTERVAL)]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,  # If preceding run is still running, skip the new one - this is simplest
            catchup_window=PROACTIVE_TASKS_SCHEDULE_INTERVAL,  # After Temporal is down, only catch up on the last PROACTIVE_TASKS_SCHEDULE_INTERVAL of missed runs
        ),
    )

    schedule_id = "video-segment-clustering-coordinator-schedule"
    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, coordinator_schedule)
    else:
        await a_create_schedule(
            client,
            schedule_id,
            coordinator_schedule,
            trigger_immediately=False,
        )
