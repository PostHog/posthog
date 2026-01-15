"""Priority calculation for video segment clustering.

Priority is calculated based on number of unique users affected.
"""

import math
from datetime import datetime, timedelta
from typing import TypedDict

from asgiref.sync import sync_to_async

from posthog.models.team import Team
from posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment import _parse_timestamp_to_seconds
from posthog.temporal.ai.video_segment_clustering.data import count_distinct_persons
from posthog.temporal.ai.video_segment_clustering.models import VideoSegmentMetadata


class TaskMetrics(TypedDict):
    relevant_user_count: int
    occurrence_count: int
    last_occurrence_at: datetime | None


async def calculate_task_metrics(team: Team, segments: list[VideoSegmentMetadata]) -> TaskMetrics:
    if not segments:
        return TaskMetrics(
            relevant_user_count=0,
            occurrence_count=0,
            last_occurrence_at=None,
        )

    # Count unique persons via SQL (a person can have multiple distinct_ids)
    distinct_ids = [segment.distinct_id for segment in segments]
    relevant_user_count = await sync_to_async(count_distinct_persons)(team, distinct_ids)

    # Find most recent occurrence
    last_occurrence_at = None
    for segment in segments:
        session_start_time = datetime.fromisoformat(segment.session_start_time)
        segment_start_time = session_start_time + timedelta(seconds=_parse_timestamp_to_seconds(segment.start_time))
        if last_occurrence_at is None or segment_start_time > last_occurrence_at:
            last_occurrence_at = segment_start_time

    return TaskMetrics(
        relevant_user_count=relevant_user_count,
        occurrence_count=len(segments),
        last_occurrence_at=last_occurrence_at,
    )


def calculate_priority_score(*, relevant_user_count: int) -> float:
    """
    Calculate priority score for a task.

    Currently incredibly simple (just user count), but in the future we'll want to include
    the actual impact of the issue on the user.
    """
    return math.log(1 + relevant_user_count)
