"""Priority calculation for video segment clustering.

Priority is calculated based on number of unique users affected.
"""

import math
from datetime import datetime

from asgiref.sync import sync_to_async

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering.data import count_distinct_persons
from posthog.temporal.ai.video_segment_clustering.models import VideoSegmentMetadata


def calculate_priority_score(distinct_user_count: int) -> float:
    """Calculate priority score for a task.

    Formula: priority = log(1 + user_count)

    We use log for user count to avoid outliers dominating.

    Args:
        distinct_user_count: Number of unique users affected

    Returns:
        Priority score (higher = more urgent)
    """
    return math.log(1 + distinct_user_count)


async def calculate_task_metrics(team: Team, segments: list[VideoSegmentMetadata]) -> dict:
    """Calculate aggregate metrics for a task from its segments.

    Args:
        team_id: Team ID for the HogQL query
        segments: List of video segment metadata

    Returns:
        Dictionary with distinct_user_count, occurrence_count, last_occurrence_at
    """
    if not segments:
        return {
            "distinct_user_count": 0,
            "occurrence_count": 0,
            "last_occurrence_at": None,
        }

    # Count unique persons via SQL (a person can have multiple distinct_ids)
    distinct_ids = [segment.distinct_id for segment in segments if segment.distinct_id]
    distinct_user_count = await sync_to_async(count_distinct_persons)(team, distinct_ids)

    # Find most recent occurrence
    timestamps = []
    for segment in segments:
        if segment.timestamp:
            try:
                ts = datetime.fromisoformat(segment.timestamp.replace("Z", "+00:00"))
                timestamps.append(ts)
            except ValueError:
                pass

    last_occurrence_at = max(timestamps) if timestamps else None

    return {
        "distinct_user_count": distinct_user_count,
        "occurrence_count": len(segments),
        "last_occurrence_at": last_occurrence_at,
    }
