"""Data access layer for trace clustering.

This module consolidates all HogQL queries used by the clustering workflow,
providing a single source of truth for data fetching operations.
All queries are team-scoped through HogQL's automatic team filtering.
"""

from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models.team import Team
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.models import TraceEmbeddings, TraceId, TraceSummaries

# AI event types to query for trace filtering (same as TracesQueryRunner)
AI_EVENT_TYPES = ("$ai_span", "$ai_generation", "$ai_embedding", "$ai_metric", "$ai_feedback", "$ai_trace")


def fetch_eligible_trace_ids(
    team: Team,
    window_start: datetime,
    window_end: datetime,
    trace_filters: list[dict],
    max_samples: int,
) -> list[TraceId]:
    """Query trace IDs that have at least one AI event matching the given property filters.

    Queries across all AI event types ($ai_span, $ai_generation, $ai_embedding, etc.)
    to find traces where at least one event matches the filter criteria. This allows
    filtering on properties from any event type (e.g., $ai_model on generations,
    custom properties on spans, etc.).

    Args:
        team: Team object to query traces for
        window_start: Start of time window
        window_end: End of time window
        trace_filters: List of property filter dicts (PostHog standard format)
        max_samples: Maximum number of traces to return

    Returns:
        List of trace IDs where at least one event matches the filter criteria
    """
    if not trace_filters:
        return []

    # Build property filter expression from the list of filters
    property_exprs: list[ast.Expr] = []
    for prop in trace_filters:
        property_exprs.append(property_to_expr(prop, team))

    # Combine filters with AND logic
    property_filter_expr = ast.And(exprs=property_exprs) if len(property_exprs) > 1 else property_exprs[0]

    # Build event types tuple for IN clause
    event_types_tuple = ast.Tuple(exprs=[ast.Constant(value=e) for e in AI_EVENT_TYPES])

    query = parse_select(
        """
        SELECT DISTINCT properties.$ai_trace_id as trace_id
        FROM events
        WHERE event IN {event_types}
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND isNotNull(properties.$ai_trace_id)
            AND properties.$ai_trace_id != ''
            AND {property_filters}
        ORDER BY rand()
        LIMIT {max_samples}
        """
    )

    with tags_context(product=Product.LLM_ANALYTICS):
        result = execute_hogql_query(
            query_type="EligibleTraceIdsForClustering",
            query=query,
            placeholders={
                "event_types": event_types_tuple,
                "start_dt": ast.Constant(value=window_start),
                "end_dt": ast.Constant(value=window_end),
                "property_filters": property_filter_expr,
                "max_samples": ast.Constant(value=max_samples * 2),  # Oversample to account for missing embeddings
            },
            team=team,
        )

    rows = result.results or []
    return [row[0] for row in rows if row[0]]


def fetch_trace_embeddings_for_clustering(
    team: Team,
    window_start: datetime,
    window_end: datetime,
    max_samples: int,
    trace_filters: list[dict] | None = None,
) -> tuple[list[TraceId], TraceEmbeddings]:
    """Query trace IDs and embeddings from document_embeddings table using HogQL.

    If trace_filters are provided, first queries for eligible trace IDs from AI events
    matching the filter criteria, then fetches embeddings only for those traces.

    Args:
        team: Team object to query embeddings for
        window_start: Start of time window
        window_end: End of time window
        max_samples: Maximum number of traces to sample
        trace_filters: Optional property filters to scope which traces are included

    Returns:
        Tuple of (list of trace IDs, dict mapping trace_id -> embedding vector)
    """
    # If filters provided, first get eligible trace IDs
    eligible_trace_ids: list[TraceId] | None = None
    if trace_filters:
        eligible_trace_ids = fetch_eligible_trace_ids(
            team=team,
            window_start=window_start,
            window_end=window_end,
            trace_filters=trace_filters,
            max_samples=max_samples,
        )
        # If no traces match filters, return early
        if not eligible_trace_ids:
            return [], {}

    # Build base query - add IN clause if we have eligible trace IDs
    if eligible_trace_ids:
        query = parse_select(
            """
            SELECT document_id, embedding
            FROM raw_document_embeddings
            WHERE timestamp >= {start_dt}
                AND timestamp < {end_dt}
                AND product = {product}
                AND document_type = {document_type}
                AND rendering = {rendering}
                AND length(embedding) > 0
                AND document_id IN {eligible_ids}
            ORDER BY rand()
            LIMIT {max_samples}
            """
        )
        eligible_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=tid) for tid in eligible_trace_ids])
    else:
        query = parse_select(
            """
            SELECT document_id, embedding
            FROM raw_document_embeddings
            WHERE timestamp >= {start_dt}
                AND timestamp < {end_dt}
                AND product = {product}
                AND document_type = {document_type}
                AND rendering = {rendering}
                AND length(embedding) > 0
            ORDER BY rand()
            LIMIT {max_samples}
            """
        )
        eligible_ids_tuple = None

    placeholders = {
        "start_dt": ast.Constant(value=window_start),
        "end_dt": ast.Constant(value=window_end),
        "product": ast.Constant(value=constants.LLMA_TRACE_PRODUCT),
        "document_type": ast.Constant(value=constants.LLMA_TRACE_DOCUMENT_TYPE),
        "rendering": ast.Constant(value=constants.LLMA_TRACE_DETAILED_RENDERING),
        "max_samples": ast.Constant(value=max_samples),
    }
    if eligible_ids_tuple:
        placeholders["eligible_ids"] = eligible_ids_tuple

    with tags_context(product=Product.LLM_ANALYTICS):
        result = execute_hogql_query(
            query_type="TraceEmbeddingsForClustering",
            query=query,
            placeholders=placeholders,
            team=team,
        )

    rows = result.results or []

    # Build both in single loop to ensure trace_ids and embeddings_map are in same order
    trace_ids: list[TraceId] = []
    embeddings_map: TraceEmbeddings = {}
    for row in rows:
        trace_id = row[0]
        trace_ids.append(trace_id)
        embeddings_map[trace_id] = row[1]

    return trace_ids, embeddings_map


def fetch_trace_summaries(
    team: Team,
    trace_ids: list[TraceId],
    window_start: datetime,
    window_end: datetime,
) -> TraceSummaries:
    """Fetch trace summaries from $ai_trace_summary events using HogQL.

    Args:
        team: Team object (for HogQL team-scoped queries)
        trace_ids: List of trace IDs to fetch summaries for
        window_start: Start of time window
        window_end: End of time window

    Returns:
        Dictionary mapping trace_id -> {title, flow_diagram, bullets, interesting_notes}
    """
    if not trace_ids:
        return {}

    query = parse_select(
        """
        SELECT
            properties.$ai_trace_id as trace_id,
            properties.$ai_summary_title as title,
            properties.$ai_summary_flow_diagram as flow_diagram,
            properties.$ai_summary_bullets as bullets,
            properties.$ai_summary_interesting_notes as interesting_notes
        FROM events
        WHERE event = {event_name}
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND properties.$ai_trace_id IN {trace_ids}
        """
    )

    # Build trace_ids tuple for IN clause
    trace_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=tid) for tid in trace_ids])

    with tags_context(product=Product.LLM_ANALYTICS):
        result = execute_hogql_query(
            query_type="TraceSummariesForClustering",
            query=query,
            placeholders={
                "event_name": ast.Constant(value="$ai_trace_summary"),
                "start_dt": ast.Constant(value=window_start),
                "end_dt": ast.Constant(value=window_end),
                "trace_ids": trace_ids_tuple,
            },
            team=team,
        )

    rows = result.results or []
    trace_summaries: TraceSummaries = {
        row[0]: {
            "title": row[1],
            "flow_diagram": row[2],
            "bullets": row[3],
            "interesting_notes": row[4],
        }
        for row in rows
    }

    return trace_summaries
