"""Schedule configuration for video segment clustering coordinator."""

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.coordinator import VideoSegmentClusteringCoordinatorInputs
from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule

SCHEDULE_ID = "video-segment-clustering-coordinator-schedule"


async def create_video_segment_clustering_schedule(client: Client):
    """Create or update the schedule for video segment clustering.

    The coordinator discovers teams via feature flag and spawns child workflows
    to cluster video segments for each team.

    This schedule runs every 30 minutes.
    """
    coordinator_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "video-segment-clustering-coordinator",
            VideoSegmentClusteringCoordinatorInputs(
                lookback_hours=int(constants.DEFAULT_LOOKBACK_WINDOW.total_seconds() / 3600),
                min_segments=constants.MIN_SEGMENTS_FOR_CLUSTERING,
                max_concurrent_teams=constants.MAX_CONCURRENT_TEAMS,
            ),
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=constants.CLUSTERING_INTERVAL)]),
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


async def delete_video_segment_clustering_schedule(client: Client):
    """Delete the video segment clustering coordinator schedule.

    Args:
        client: Temporal client
    """
    await a_delete_schedule(client, SCHEDULE_ID)
