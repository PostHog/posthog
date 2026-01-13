"""
Activity 2 of the video segment clustering workflow:
Fetch unprocessed video segments from ClickHouse.
"""

from datetime import datetime

from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering.data import fetch_video_segments
from posthog.temporal.ai.video_segment_clustering.models import FetchSegmentsActivityInputs, FetchSegmentsResult


@activity.defn
async def fetch_segments_activity(inputs: FetchSegmentsActivityInputs) -> FetchSegmentsResult:
    """Fetch unprocessed video segments from ClickHouse.

    Queries document_embeddings for video segments that haven't been processed yet,
    based on the clustering state watermark.
    """
    team = await Team.objects.aget(id=inputs.team_id)

    since_timestamp = None
    if inputs.since_timestamp:
        since_timestamp = datetime.fromisoformat(inputs.since_timestamp.replace("Z", "+00:00"))

    return await fetch_video_segments(
        team=team,
        since_timestamp=since_timestamp,
        lookback_hours=inputs.lookback_hours,
    )
