from asgiref.sync import sync_to_async

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering import constants


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
                FROM raw_document_embeddings
                WHERE timestamp >= now() - INTERVAL {lookback_hours} HOUR
                    AND product = {product}
                    AND document_type = {document_type}
                    AND rendering = {rendering}
                    AND length(embedding) > 0
                ORDER BY timestamp ASC"""
            ),
            placeholders={
                "lookback_hours": ast.Constant(value=lookback_hours),
                "product": ast.Constant(value=constants.PRODUCT),
                "document_type": ast.Constant(value=constants.DOCUMENT_TYPE),
                "rendering": ast.Constant(value=constants.RENDERING),
            },
            team=team,
        )
    return result.results or []


@sync_to_async
def fetch_video_segment_embedding_rows(team: Team, document_ids: list[str]):
    """Fetch video segment embeddings from ClickHouse - specific segments, with embedding vectors included."""
    with tags_context(product=Product.SESSION_SUMMARY):
        result = execute_hogql_query(
            query_type="VideoSegmentEmbeddingsForClustering",
            query=parse_select(
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
                    AND rendering = {rendering}"""
            ),
            placeholders={
                "doc_ids": ast.Constant(value=document_ids),
                "product": ast.Constant(value=constants.PRODUCT),
                "document_type": ast.Constant(value=constants.DOCUMENT_TYPE),
                "rendering": ast.Constant(value=constants.RENDERING),
            },
            team=team,
        )
    return result.results or []
