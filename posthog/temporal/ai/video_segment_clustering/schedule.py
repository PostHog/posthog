"""Schedule configuration for hourly video segment clustering coordinator."""

from datetime import timedelta

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.ai.video_segment_clustering.constants import DEFAULT_LOOKBACK_WINDOW
from posthog.temporal.ai.video_segment_clustering.coordinator_workflow import VideoSegmentClusteringCoordinatorInputs
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule


async def create_video_segment_clustering_coordinator_schedule(client: Client):
    """Run task inference on schedule."""
    coordinator_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "video-segment-clustering-coordinator",
            VideoSegmentClusteringCoordinatorInputs(
                lookback_hours=int(DEFAULT_LOOKBACK_WINDOW.total_seconds() / 3600),
            ),
            id="video-segment-clustering-coordinator-schedule",
            task_queue=settings.MAX_AI_TASK_QUEUE,
        ),
        # FIXME: 1min just for testing, before merging we'll change this to 1h
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=1))]),
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
