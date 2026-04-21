"""Configuration constants for the video segment clustering module (orchestration + schedule)."""

from datetime import timedelta
from uuid import UUID


def clustering_workflow_id(team_id: int, config_id: UUID | str) -> str:
    """Shared workflow ID for conflict resolution between initial trigger and coordinator."""
    return f"video-segment-clustering-team-{team_id}-config-{config_id}"


# Period considered for priming / coordinator inputs, and how often the coordinator runs
DEFAULT_LOOKBACK_WINDOW = timedelta(days=7)
PROACTIVE_TASKS_SCHEDULE_INTERVAL = timedelta(hours=1)
