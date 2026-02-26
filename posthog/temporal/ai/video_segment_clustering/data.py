from asgiref.sync import sync_to_async

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models.team import Team
from posthog.temporal.ai.session_summary.activities.a5_embed_and_store_segments import SESSION_SEGMENTS_EMBEDDING_MODEL

MAX_SEGMENTS_RETURNED = 50_000


def count_distinct_persons(team: Team, distinct_ids: list[str]) -> int:
    """Count unique persons from a list of distinct_ids, using ClickHouse as the source of truth.

    (This util should probably be more general than video_segment_clustering, but really unsure what the right place is.)
    """
    if not distinct_ids:
        return 0
    result = execute_hogql_query(
        query_type="DistinctPersonCount",
        query=parse_select(
            """
            SELECT COUNT(DISTINCT person_id)
            FROM person_distinct_ids
            WHERE distinct_id IN {distinct_ids}"""
        ),
        placeholders={"distinct_ids": ast.Constant(value=distinct_ids)},
        team=team,
    )
    return result.results[0][0] if result.results and len(result.results) > 0 else 0


@sync_to_async
def fetch_video_segment_metadata_rows(team: Team, lookback_hours: int):
    """Fetch recent video segment metadata from ClickHouse - just metadata, without embedding vectors."""
    with tags_context(product=Product.SESSION_SUMMARY):
        result = execute_hogql_query(
            query_type="VideoSegmentMetadataForClustering",
            query=parse_select(
                # Note: We don't select embedding here to avoid large payloads
                """
                SELECT
                    document_id,
                    content,
                    metadata,
                    timestamp
                FROM document_embeddings
                WHERE timestamp >= now() - INTERVAL {lookback_hours} HOUR
                    AND model_name = {model_name}
                    AND product = {product}
                    AND document_type = {document_type}
                    AND rendering = {rendering}
                ORDER BY timestamp ASC
                LIMIT {max_segments_returned}"""
            ),
            placeholders={
                "lookback_hours": ast.Constant(value=lookback_hours),
                "model_name": ast.Constant(value=SESSION_SEGMENTS_EMBEDDING_MODEL.value),
                "product": ast.Constant(value="session-replay"),
                "document_type": ast.Constant(value="video-segment"),
                "rendering": ast.Constant(value="video-analysis"),
                "max_segments_returned": ast.Constant(value=MAX_SEGMENTS_RETURNED),
            },
            team=team,
        )
    return result.results or []


@sync_to_async
def fetch_video_segment_embedding_vectors(team: Team, document_ids: list[str]) -> dict[str, list[float]]:
    """Fetch only embedding vectors from ClickHouse, keyed by document_id.

    All other segment metadata is loaded from S3 (see state.py), so this only
    needs to return the vectors themselves for clustering.
    """
    if not document_ids:
        return {}
    with tags_context(product=Product.SESSION_SUMMARY):
        result = execute_hogql_query(
            query_type="VideoSegmentEmbeddingsForClustering",
            query=parse_select(
                """
                SELECT document_id, embedding
                FROM document_embeddings
                WHERE document_id IN {doc_ids}
                    AND model_name = {model_name}
                    AND product = {product}
                    AND document_type = {document_type}
                    AND rendering = {rendering}
                LIMIT {max_segments_returned}"""
            ),
            placeholders={
                "doc_ids": ast.Constant(value=document_ids),
                "model_name": ast.Constant(value=SESSION_SEGMENTS_EMBEDDING_MODEL.value),
                "product": ast.Constant(value="session-replay"),
                "document_type": ast.Constant(value="video-segment"),
                "rendering": ast.Constant(value="video-analysis"),
                "max_segments_returned": ast.Constant(value=MAX_SEGMENTS_RETURNED),
            },
            team=team,
        )
    return {row[0]: row[1] for row in (result.results or [])}
