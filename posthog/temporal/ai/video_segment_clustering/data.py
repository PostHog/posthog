"""Data access layer for video segment clustering.

This module handles all HogQL queries for fetching video segment embeddings
and related session data for the clustering workflow.
"""

import json
from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.models import FetchSegmentsResult, VideoSegment


def fetch_video_segments(
    team: Team,
    since_timestamp: datetime | None,
    lookback_hours: int,
) -> FetchSegmentsResult:
    """Fetch video segment embeddings from document_embeddings table.

    Args:
        team: Team object to query for
        since_timestamp: Only fetch segments after this timestamp (for incremental processing)
        lookback_hours: How far back to look if since_timestamp is None

    Returns:
        FetchSegmentsResult with list of segments and latest timestamp
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

    query = parse_select(
        f"""
        SELECT
            document_id,
            content,
            embedding,
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

    with tags_context(product=Product.REPLAY):
        result = execute_hogql_query(
            query_type="VideoSegmentEmbeddingsForClustering",
            query=query,
            placeholders=placeholders,
            team=team,
        )

    rows = result.results or []
    segments: list[VideoSegment] = []
    latest_timestamp: str | None = None

    for row in rows:
        document_id = row[0]
        content = row[1]
        embedding = row[2]
        metadata_str = row[3]
        timestamp = row[4]

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
            VideoSegment(
                document_id=document_id,
                session_id=session_id,
                start_time=start_time,
                end_time=end_time,
                distinct_id=distinct_id,
                content=content,
                embedding=embedding,
                timestamp=timestamp_str if timestamp else "",
            )
        )

    return FetchSegmentsResult(
        segments=segments,
        latest_timestamp=latest_timestamp,
    )


def fetch_existing_task_centroids(team: Team) -> dict[str, list[float]]:
    """Fetch cluster centroids from existing Tasks for deduplication.

    Args:
        team: Team object

    Returns:
        Dictionary mapping task_id -> centroid embedding
    """
    from products.tasks.backend.models import Task

    tasks = Task.objects.filter(
        team=team,
        origin_product=Task.OriginProduct.SESSION_SUMMARIES,
        deleted=False,
        cluster_centroid__isnull=False,
    ).values("id", "cluster_centroid")

    return {str(task["id"]): task["cluster_centroid"] for task in tasks}
