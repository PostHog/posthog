"""Data access layer for video segment clustering.

This module handles all HogQL queries for fetching video segment embeddings
and related session data for the clustering workflow.
"""

import json
from datetime import datetime

from posthog.schema import PropertyOperator, RecordingPropertyFilter, RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models.team import Team
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.models import FetchSegmentsResult, VideoSegment, VideoSegmentMetadata

from products.tasks.backend.models import Task

from ee.hogai.session_summaries.constants import MIN_SESSION_DURATION_FOR_SUMMARY_MS


def fetch_video_segments(
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

    with tags_context(product=Product.REPLAY):
        result = execute_hogql_query(
            query_type="VideoSegmentMetadataForClustering",
            query=query,
            placeholders=placeholders,
            team=team,
        )

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


def fetch_embeddings_by_document_ids(
    team: Team,
    document_ids: list[str],
) -> list[VideoSegment]:
    """Fetch video segments with embeddings for specific document IDs.

    Used by clustering activity to fetch embeddings only when needed,
    avoiding large payloads in Temporal activity inputs/outputs.

    Args:
        team: Team object to query for
        document_ids: List of document IDs to fetch

    Returns:
        List of VideoSegment objects with embeddings
    """
    if not document_ids:
        return []

    query = parse_select(
        """
        SELECT
            document_id,
            content,
            embedding,
            metadata,
            timestamp
        FROM raw_document_embeddings
        WHERE document_id IN {doc_ids}
            AND product = {product}
            AND document_type = {document_type}
            AND rendering = {rendering}
        """
    )

    placeholders = {
        "doc_ids": ast.Constant(value=document_ids),
        "product": ast.Constant(value=constants.PRODUCT),
        "document_type": ast.Constant(value=constants.DOCUMENT_TYPE),
        "rendering": ast.Constant(value=constants.RENDERING),
    }

    with tags_context(product=Product.REPLAY):
        result = execute_hogql_query(
            query_type="VideoSegmentEmbeddingsForClustering",
            query=query,
            placeholders=placeholders,
            team=team,
        )

    rows = result.results or []
    segments: list[VideoSegment] = []

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
            session_id = metadata.get("session_id", "")
            start_time = metadata.get("start_time", "")
            end_time = metadata.get("end_time", "")

        distinct_id = metadata.get("distinct_id", "")
        timestamp_str = (
            timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp) if timestamp else ""
        )

        segments.append(
            VideoSegment(
                document_id=document_id,
                session_id=session_id,
                start_time=start_time,
                end_time=end_time,
                distinct_id=distinct_id,
                content=content,
                embedding=embedding,
                timestamp=timestamp_str,
            )
        )

    return segments


def fetch_recent_session_ids(team: Team, lookback_hours: int) -> list[str]:
    """Fetch session IDs of recordings that ended within the lookback period.

    Uses RecordingsQuery for consistency with the session recordings API, ensuring:
    - Full test account filtering (not just person properties)
    - Expiry/retention period checks (excludes expired recordings)
    - Minimum duration threshold (MIN_SESSION_DURATION_FOR_SUMMARY_MS)
    - Finished sessions only (ongoing = False, i.e., last event > 5 minutes ago)

    Args:
        team: Team object to query for
        lookback_hours: How far back to look for ended recordings

    Returns:
        List of session IDs of finished recordings in the timeframe
    """
    min_duration_seconds = MIN_SESSION_DURATION_FOR_SUMMARY_MS / 1000

    query = RecordingsQuery(
        filter_test_accounts=True,
        date_from=f"-{lookback_hours}h",
        having_predicates=[
            RecordingPropertyFilter(
                key="duration",
                operator=PropertyOperator.GTE,
                value=min_duration_seconds,
            ),
            RecordingPropertyFilter(
                key="ongoing",
                operator=PropertyOperator.EXACT,
                value=0,  # ongoing is UInt8 in ClickHouse (0 = finished, 1 = ongoing)
            ),
        ],
    )

    with tags_context(product=Product.REPLAY):
        result = SessionRecordingListFromQuery(team=team, query=query).run()

    return [recording["session_id"] for recording in result.results]


def fetch_existing_task_centroids(team: Team) -> dict[str, list[float]]:
    """Fetch cluster centroids from existing Tasks for deduplication.

    Args:
        team: Team object

    Returns:
        Dictionary mapping task_id -> centroid embedding
    """
    tasks = Task.objects.filter(
        team=team,
        origin_product=Task.OriginProduct.SESSION_SUMMARIES,
        deleted=False,
        cluster_centroid__isnull=False,
    ).values("id", "cluster_centroid")

    return {str(task["id"]): task["cluster_centroid"] for task in tasks}
