"""
Activity 2 of the video segment clustering workflow:
Fetch unprocessed video segments from ClickHouse.
"""

import json
from datetime import datetime

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.models import (
    FetchSegmentsActivityInputs,
    FetchSegmentsResult,
    VideoSegmentMetadata,
)


@activity.defn
async def fetch_segments_activity(inputs: FetchSegmentsActivityInputs) -> FetchSegmentsResult:
    """Fetch video segments from ClickHouse.

    Queries document_embeddings for video segments that haven't been processed yet,
    based on the clustering state watermark (since_timestamp).
    """
    team = await Team.objects.aget(id=inputs.team_id)

    since_timestamp = None
    if inputs.since_timestamp:
        since_timestamp = datetime.fromisoformat(inputs.since_timestamp.replace("Z", "+00:00"))

    return await _fetch_video_segments(
        team=team,
        since_timestamp=since_timestamp,
        lookback_hours=inputs.lookback_hours,
    )


async def _fetch_video_segments(
    team: Team,
    since_timestamp: datetime | None,
    lookback_hours: int,
) -> FetchSegmentsResult:
    """Fetch video segment metadata from document_embeddings table (no embeddings).

    Args:
        team: Team object to query for
        since_timestamp: Only fetch segments after this timestamp (for incremental processing)
        lookback_hours: How far back to look if since_timestamp is None

    Returns:
        FetchSegmentsResult with list of segment metadata and latest timestamp
    """
    # Build time filter
    if since_timestamp:
        time_filter = "timestamp > {since_ts}"
        placeholders = {
            "since_ts": ast.Constant(value=since_timestamp),
        }
    else:
        time_filter = "timestamp >= now() - INTERVAL {hours} HOUR"
        placeholders = {
            "hours": ast.Constant(value=lookback_hours),
        }

    # Note: We don't select embedding here to avoid large payloads
    query = parse_select(
        f"""
        SELECT
            document_id,
            content,
            metadata,
            timestamp
        FROM raw_document_embeddings
        WHERE {time_filter}
            AND product = {{product}}
            AND document_type = {{document_type}}
            AND rendering = {{rendering}}
            AND length(embedding) > 0
        ORDER BY timestamp ASC
        """
    )

    placeholders.update(
        {
            "product": ast.Constant(value=constants.PRODUCT),
            "document_type": ast.Constant(value=constants.DOCUMENT_TYPE),
            "rendering": ast.Constant(value=constants.RENDERING),
        }
    )

    @sync_to_async
    def _execute_query():
        with tags_context(product=Product.REPLAY):
            return execute_hogql_query(
                query_type="VideoSegmentMetadataForClustering",
                query=query,
                placeholders=placeholders,
                team=team,
            )

    result = await _execute_query()

    rows = result.results or []
    segments: list[VideoSegmentMetadata] = []
    latest_timestamp: str | None = None

    for row in rows:
        document_id = row[0]
        content = row[1]
        metadata_str = row[2]
        timestamp = row[3]

        # Parse metadata JSON
        try:
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        # Parse document_id format: "{session_id}:{start_time}:{end_time}"
        parts = document_id.split(":")
        if len(parts) >= 3:
            session_id = parts[0]
            start_time = parts[1]
            end_time = parts[2]
        else:
            # Fallback to metadata
            session_id = metadata.get("session_id", "")
            start_time = metadata.get("start_time", "")
            end_time = metadata.get("end_time", "")

        distinct_id = metadata.get("distinct_id", "")

        # Track latest timestamp
        if timestamp:
            timestamp_str = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
            latest_timestamp = timestamp_str

        segments.append(
            VideoSegmentMetadata(
                document_id=document_id,
                session_id=session_id,
                start_time=start_time,
                end_time=end_time,
                distinct_id=distinct_id,
                content=content,
                timestamp=timestamp_str if timestamp else "",
            )
        )

    return FetchSegmentsResult(
        segments=segments,
        latest_timestamp=latest_timestamp,
    )
