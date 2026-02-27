"""
Activity 2 of the video segment clustering workflow:
Fetch unprocessed video segments from ClickHouse.

Stores result in object storage to avoid exceeding Temporal's 2 MB payload limit.
"""

import json

from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering.models import (
    FetchSegmentsActivityInputs,
    FetchSegmentsResult,
    VideoSegment,
)
from posthog.temporal.ai.video_segment_clustering.object_storage import generate_storage_key, store_fetch_result
from posthog.temporal.common.logger import get_logger

from ..data import fetch_video_segment_rows

logger = get_logger(__name__)


@activity.defn
async def fetch_segments_activity(inputs: FetchSegmentsActivityInputs) -> FetchSegmentsResult:
    """Fetch video segments from ClickHouse.

    Queries document_embeddings for video segments within the lookback window.
    Uses a configurable lookback period (default 7 days) to ensure idempotent
    processing - segments are deduplicated at the Task and TaskReference level.
    """

    team = await Team.objects.aget(id=inputs.team_id)
    video_segment_rows = await fetch_video_segment_rows(
        team=team,
        lookback_hours=inputs.lookback_hours,
    )
    segments: list[VideoSegment] = []
    parse_errors = 0
    missing_metadata = 0

    for row in video_segment_rows:
        document_id, content, metadata_str, embedding = row
        try:
            # Parse metadata JSON
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
        except (json.JSONDecodeError, TypeError):
            # Being defensive to avoid a poison pill kind of situation
            logger.exception(f"Failed to parse metadata for document_id: {document_id}", metadata_str=metadata_str)
            parse_errors += 1
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
            missing_metadata += 1
            continue

        segments.append(
            VideoSegment(
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
                embedding=embedding,
            )
        )

    distinct_ids = list({s.distinct_id for s in segments if s.distinct_id})
    storage_key = generate_storage_key(inputs.team_id, activity.info().workflow_run_id, name="segments")
    await store_fetch_result(storage_key, segments, distinct_ids)

    return FetchSegmentsResult(storage_key=storage_key, document_count=len(segments))
