"""
Activity 2 of the video segment clustering workflow:
Fetch unprocessed video segments from ClickHouse.
"""

import json

from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering.models import (
    FetchSegmentsActivityInputs,
    FetchSegmentsResult,
    VideoSegmentMetadata,
)
from posthog.temporal.common.logger import get_logger

from ..data import fetch_video_segment_metadata_rows

logger = get_logger(__name__)


@activity.defn
async def fetch_segments_activity(inputs: FetchSegmentsActivityInputs) -> FetchSegmentsResult:
    """Fetch video segments from ClickHouse.

    Queries document_embeddings for video segments within the lookback window.
    Uses a configurable lookback period (default 7 days) to ensure idempotent
    processing - segments are deduplicated at the Task and TaskReference level.
    """
    team = await Team.objects.aget(id=inputs.team_id)
    video_segment_metadata_rows = await fetch_video_segment_metadata_rows(
        team=team,
        lookback_hours=inputs.lookback_hours,
    )
    segments: list[VideoSegmentMetadata] = []

    for row in video_segment_metadata_rows:
        document_id, content, metadata_str, _timestamp_of_embedding = row
        # Parse metadata JSON
        try:
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
        except (json.JSONDecodeError, TypeError):
            # Being defensive to avoid a poison pill kind of situation
            logger.exception(f"Failed to parse metadata for document_id: {document_id}", metadata_str=metadata_str)
            continue

        session_id = metadata.get("session_id")
        start_time = metadata.get("start_time")
        end_time = metadata.get("end_time")
        distinct_id = metadata.get("distinct_id")
        session_start_time = metadata.get("session_start_time")
        session_end_time = metadata.get("session_end_time")
        session_duration = metadata.get("session_duration")
        session_active_seconds = metadata.get("session_active_seconds")
        if (
            not session_id
            or not start_time
            or not end_time
            or not distinct_id
            or not session_start_time
            or not session_end_time
            or not session_duration
            or not session_active_seconds
        ):
            logger.error(f"Missing required metadata for document_id: {document_id}", metadata=metadata)
            continue

        segments.append(
            VideoSegmentMetadata(
                document_id=document_id,
                session_id=session_id,
                start_time=start_time,
                end_time=end_time,
                session_start_time=session_start_time,
                session_end_time=session_end_time,
                session_duration=session_duration,
                session_active_seconds=session_active_seconds,
                distinct_id=distinct_id,
                content=content,
            )
        )

    return FetchSegmentsResult(segments=segments)
