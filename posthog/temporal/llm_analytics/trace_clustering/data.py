"""Data access layer for trace clustering.

This module consolidates all HogQL queries used by the clustering workflow,
providing a single source of truth for data fetching operations.
All queries are team-scoped through HogQL's automatic team filtering.
"""

from datetime import datetime

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.models import (
    AnalysisLevel,
    ItemBatchRunIds,
    ItemEmbeddings,
    ItemId,
    ItemSummaries,
)

logger = structlog.get_logger(__name__)

# ClickHouse max_execution_time for clustering queries (seconds).
# Default HogQL timeout is 60s which is too tight for the legacy unfiltered
# query path on high-volume teams. These run in background Temporal activities.
CLUSTERING_QUERY_MAX_EXECUTION_TIME = 120


def fetch_item_embeddings_for_clustering(
    team: Team,
    window_start: datetime,
    window_end: datetime,
    max_samples: int,
    analysis_level: AnalysisLevel = "trace",
    job_id: str | None = None,
) -> tuple[list[ItemId], ItemEmbeddings, ItemBatchRunIds]:
    """Query item IDs and embeddings from document_embeddings table.

    Two paths:
    - job_id present: filter by rendering suffix (batch_run_id = {team}_{ts}_{job_id})
    - no job_id: return all embeddings for the document type (legacy/unfiltered)
    """
    document_type = (
        constants.LLMA_GENERATION_DOCUMENT_TYPE
        if analysis_level == "generation"
        else constants.LLMA_TRACE_DOCUMENT_TYPE
    )

    if job_id:
        query = parse_select(
            """
            SELECT document_id, embedding, rendering
            FROM raw_document_embeddings
            WHERE timestamp >= {start_dt}
                AND timestamp < {end_dt}
                AND product = {product}
                AND document_type = {document_type}
                AND length(embedding) > 0
                AND endsWith(rendering, {job_id_suffix})
            ORDER BY rand()
            LIMIT {max_samples}
            """
        )
    else:
        query = parse_select(
            """
            SELECT document_id, embedding, rendering
            FROM raw_document_embeddings
            WHERE timestamp >= {start_dt}
                AND timestamp < {end_dt}
                AND product = {product}
                AND (
                    document_type = {document_type}
                    OR (document_type = {document_type_legacy} AND rendering = {rendering_legacy})
                )
                AND length(embedding) > 0
            ORDER BY rand()
            LIMIT {max_samples}
            """
        )

    placeholders: dict[str, ast.Expr] = {
        "start_dt": ast.Constant(value=window_start),
        "end_dt": ast.Constant(value=window_end),
        "product": ast.Constant(value=constants.LLMA_TRACE_PRODUCT),
        "document_type": ast.Constant(value=document_type),
        "max_samples": ast.Constant(value=max_samples),
    }

    if job_id:
        placeholders["job_id_suffix"] = ast.Constant(value=f"_{job_id}")
    else:
        placeholders["document_type_legacy"] = ast.Constant(value=constants.LLMA_TRACE_DOCUMENT_TYPE_LEGACY)
        placeholders["rendering_legacy"] = ast.Constant(value=constants.LLMA_TRACE_RENDERING_LEGACY)

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY):
        result = execute_hogql_query(
            query_type="ItemEmbeddingsForClustering",
            query=query,
            placeholders=placeholders,
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=CLUSTERING_QUERY_MAX_EXECUTION_TIME),
        )

    rows = result.results or []

    logger.info(
        "fetch_item_embeddings_for_clustering_result",
        num_rows=len(rows),
        analysis_level=analysis_level,
        job_id=job_id,
    )

    # Build all maps in single loop to ensure item_ids, embeddings_map, and batch_run_ids are aligned
    item_ids: list[ItemId] = []
    embeddings_map: ItemEmbeddings = {}
    batch_run_ids_map: ItemBatchRunIds = {}

    # Legacy rendering values that are NOT batch_run_ids
    legacy_rendering_values = {
        constants.LLMA_TRACE_RENDERING_LEGACY,  # "llma_trace_detailed"
        "llma_trace_minimal",  # Other legacy mode
    }

    for row in rows:
        item_id = row[0]
        item_ids.append(item_id)
        embeddings_map[item_id] = row[1]

        # Only store as batch_run_id if it's not a legacy rendering constant
        # Legacy embeddings have rendering like "llma_trace_detailed"
        # New embeddings have rendering = batch_run_id (e.g., "1_2025-12-13T...")
        rendering_value = row[2]
        if rendering_value and rendering_value not in legacy_rendering_values:
            batch_run_ids_map[item_id] = rendering_value

    return item_ids, embeddings_map, batch_run_ids_map


def fetch_item_summaries(
    team: Team,
    item_ids: list[ItemId],
    batch_run_ids: ItemBatchRunIds,
    window_start: datetime,
    window_end: datetime,
    analysis_level: AnalysisLevel = "trace",
) -> ItemSummaries:
    """Fetch item summaries from $ai_trace_summary or $ai_generation_summary events using HogQL.

    Filters summaries to only return those matching the batch_run_id from the embeddings,
    ensuring we get the summary from the same summarization run as the embedding.

    Args:
        team: Team object (for HogQL team-scoped queries)
        item_ids: List of item IDs to fetch summaries for (trace_ids or generation_ids)
        batch_run_ids: Mapping of item_id -> batch_run_id from the embeddings query
        window_start: Start of time window
        window_end: End of time window
        analysis_level: "trace" or "generation" - determines which event type to query

    Returns:
        Dictionary mapping item_id -> TraceSummary (includes trace_id for navigation)
    """
    # Select event name and ID property based on analysis_level
    event_name = "$ai_generation_summary" if analysis_level == "generation" else "$ai_trace_summary"
    id_property = "$ai_generation_id" if analysis_level == "generation" else "$ai_trace_id"
    if not item_ids:
        return {}

    # Use a high limit to handle duplicate summary events per item (some have up to 4 summaries)
    # We'll filter by batch_run_id in Python after fetching
    max_rows = len(item_ids) * 5  # Allow for duplicates

    # Use ast.Field placeholder for the ID property so HogQL can resolve materialized columns.
    # JSONExtractString would bypass materialized column optimization.
    query = parse_select(
        """
        SELECT
            {id_prop} as item_id,
            properties.$ai_summary_title as title,
            properties.$ai_summary_flow_diagram as flow_diagram,
            properties.$ai_summary_bullets as bullets,
            properties.$ai_summary_interesting_notes as interesting_notes,
            properties.trace_timestamp as trace_timestamp,
            properties.$ai_batch_run_id as batch_run_id,
            properties.$ai_trace_id as trace_id
        FROM events
        WHERE event = {event_name}
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND {id_prop} IN {item_ids}
        LIMIT {max_rows}
        """
    )

    # Build item_ids tuple for IN clause
    item_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=iid) for iid in item_ids])

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY):
        result = execute_hogql_query(
            query_type="ItemSummariesForClustering",
            query=query,
            placeholders={
                "event_name": ast.Constant(value=event_name),
                "id_prop": ast.Field(chain=["properties", id_property]),
                "start_dt": ast.Constant(value=window_start),
                "end_dt": ast.Constant(value=window_end),
                "item_ids": item_ids_tuple,
                "max_rows": ast.Constant(value=max_rows),
            },
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=CLUSTERING_QUERY_MAX_EXECUTION_TIME),
        )

    rows = result.results or []
    summaries: ItemSummaries = {}
    skipped_wrong_batch = 0

    for row in rows:
        item_id = row[0]
        summary_batch_run_id = row[6]  # $ai_batch_run_id from summary event

        # Backwards compatibility: only filter if BOTH embedding and summary have batch_run_ids
        # - Old embeddings (rendering="llma_trace_detailed") won't have batch_run_id → accept any summary
        # - Old summaries won't have $ai_batch_run_id → accept them (can't verify match)
        # - New embeddings + new summaries → only accept if batch_run_ids match
        expected_batch_run_id = batch_run_ids.get(item_id)
        if expected_batch_run_id and summary_batch_run_id and expected_batch_run_id != summary_batch_run_id:
            skipped_wrong_batch += 1
            continue

        # HogQL parses timestamp strings into datetime objects
        trace_ts = row[5]
        trace_ts_str = trace_ts.isoformat() if trace_ts else ""

        # For trace-level, trace_id is the same as item_id (fallback ok)
        # For generation-level, trace_id must come from $ai_trace_id property (no fallback)
        if analysis_level == "generation":
            trace_id = row[7]
        else:
            trace_id = row[7] if row[7] else item_id

        summaries[item_id] = {
            "title": row[1],
            "flow_diagram": row[2],
            "bullets": row[3],
            "interesting_notes": row[4],
            "trace_timestamp": trace_ts_str,
            "trace_id": trace_id,
        }

    logger.debug(
        "fetch_item_summaries_result",
        total_rows=len(rows),
        unique_item_ids=len(summaries),
        skipped_wrong_batch=skipped_wrong_batch,
    )

    return summaries
