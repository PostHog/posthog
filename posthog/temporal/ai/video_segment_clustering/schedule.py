"""Schedule configuration for video segment clustering."""

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.constants import get_proactive_tasks_team_ids
from posthog.temporal.ai.video_segment_clustering.models import ClusteringWorkflowInputs
from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule


def get_schedule_id(team_id: int) -> str:
    """Get the schedule ID for a team."""
    return f"video-segment-clustering-team-{team_id}"


async def create_video_segment_clustering_schedules(client: Client):
    """Create schedules for video segment clustering for each enabled team.

    Teams are enabled via the PROACTIVE_TASKS_TEAM_IDS environment variable.
    Each team gets its own schedule running every 30 minutes.
    """
    team_ids = get_proactive_tasks_team_ids()

    for team_id in team_ids:
        schedule_id = get_schedule_id(team_id)

        team_schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                "video-segment-clustering",
                ClusteringWorkflowInputs(
                    team_id=team_id,
                    lookback_hours=int(constants.DEFAULT_LOOKBACK_WINDOW.total_seconds() / 3600),
                    min_segments=constants.MIN_SEGMENTS_FOR_CLUSTERING,
                ),
                id=schedule_id,
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            ),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=constants.CLUSTERING_INTERVAL)]),
        )

        if await a_schedule_exists(client, schedule_id):
            await a_update_schedule(client, schedule_id, team_schedule)
        else:
            await a_create_schedule(
                client,
                schedule_id,
                team_schedule,
                trigger_immediately=False,
            )


async def delete_video_segment_clustering_schedules(client: Client):
    """Delete all video segment clustering schedules.

    Deletes schedules for all currently enabled teams.
    """
    team_ids = get_proactive_tasks_team_ids()

    for team_id in team_ids:
        schedule_id = get_schedule_id(team_id)
        try:
            await a_delete_schedule(client, schedule_id)
        except Exception:
            pass  # Schedule may not exist
