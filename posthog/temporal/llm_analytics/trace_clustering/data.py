"""Data access layer for trace clustering.

This module consolidates all HogQL queries used by the clustering workflow,
providing a single source of truth for data fetching operations.
All queries are team-scoped through HogQL's automatic team filtering.

Supports both trace-level and generation-level data fetching:
- Trace level: clusters entire traces based on trace summary embeddings
- Generation level: clusters individual $ai_generation events based on generation summary embeddings
"""

from datetime import datetime

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models.team import Team
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.models import (
    TraceBatchRunIds,
    TraceEmbeddings,
    TraceId,
    TraceSummaries,
)

from products.llm_analytics.backend.summarization.models import AnalysisLevel

logger = structlog.get_logger(__name__)

# AI event types to query for trace filtering (same as TracesQueryRunner)
AI_EVENT_TYPES = ("$ai_span", "$ai_generation", "$ai_embedding", "$ai_metric", "$ai_feedback", "$ai_trace")

# Type aliases for generation-level data
GenerationId = str
GenerationEmbeddings = dict[GenerationId, list[float]]
GenerationBatchRunIds = dict[GenerationId, str]


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
) -> tuple[list[TraceId], TraceEmbeddings, TraceBatchRunIds]:
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
        Tuple of (list of trace IDs, dict mapping trace_id -> embedding vector,
                  dict mapping trace_id -> batch_run_id for linking to summaries)
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
            return [], {}, {}

    # Build base query - add IN clause if we have eligible trace IDs
    # We also fetch rendering to link embeddings to their source summarization run
    # Backwards compatibility: support both old and new document type formats
    # - New format: document_type = "llm-trace-summary-detailed" (mode in document_type, batch_run_id in rendering)
    # - Old format: document_type = "llm-trace-summary" AND rendering = "llma_trace_detailed"
    if eligible_trace_ids:
        query = parse_select(
            """
            SELECT document_id, embedding, rendering
            FROM raw_document_embeddings
            WHERE timestamp >= {start_dt}
                AND timestamp < {end_dt}
                AND product = {product}
                AND (
                    document_type = {document_type_new}
                    OR (document_type = {document_type_legacy} AND rendering = {rendering_legacy})
                )
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
            SELECT document_id, embedding, rendering
            FROM raw_document_embeddings
            WHERE timestamp >= {start_dt}
                AND timestamp < {end_dt}
                AND product = {product}
                AND (
                    document_type = {document_type_new}
                    OR (document_type = {document_type_legacy} AND rendering = {rendering_legacy})
                )
                AND length(embedding) > 0
            ORDER BY rand()
            LIMIT {max_samples}
            """
        )
        eligible_ids_tuple = None

    placeholders: dict[str, ast.Expr] = {
        "start_dt": ast.Constant(value=window_start),
        "end_dt": ast.Constant(value=window_end),
        "product": ast.Constant(value=constants.LLMA_TRACE_PRODUCT),
        "document_type_new": ast.Constant(value=constants.LLMA_TRACE_DOCUMENT_TYPE),
        "document_type_legacy": ast.Constant(value=constants.LLMA_TRACE_DOCUMENT_TYPE_LEGACY),
        "rendering_legacy": ast.Constant(value=constants.LLMA_TRACE_RENDERING_LEGACY),
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

    logger.debug(
        "fetch_trace_embeddings_for_clustering_result",
        num_rows=len(rows),
    )

    # Build all maps in single loop to ensure trace_ids, embeddings_map, and batch_run_ids are aligned
    trace_ids: list[TraceId] = []
    embeddings_map: TraceEmbeddings = {}
    batch_run_ids_map: TraceBatchRunIds = {}

    # Legacy rendering values that are NOT batch_run_ids
    legacy_rendering_values = {
        constants.LLMA_TRACE_RENDERING_LEGACY,  # "llma_trace_detailed"
        "llma_trace_minimal",  # Other legacy mode
    }

    for row in rows:
        trace_id = row[0]
        trace_ids.append(trace_id)
        embeddings_map[trace_id] = row[1]

        # Only store as batch_run_id if it's not a legacy rendering constant
        # Legacy embeddings have rendering like "llma_trace_detailed"
        # New embeddings have rendering = batch_run_id (e.g., "1_2025-12-13T...")
        rendering_value = row[2]
        if rendering_value and rendering_value not in legacy_rendering_values:
            batch_run_ids_map[trace_id] = rendering_value

    return trace_ids, embeddings_map, batch_run_ids_map


def fetch_trace_summaries(
    team: Team,
    trace_ids: list[TraceId],
    batch_run_ids: TraceBatchRunIds,
    window_start: datetime,
    window_end: datetime,
) -> TraceSummaries:
    """Fetch trace summaries from $ai_trace_summary events using HogQL.

    Filters summaries to only return those matching the batch_run_id from the embeddings,
    ensuring we get the summary from the same summarization run as the embedding.

    Args:
        team: Team object (for HogQL team-scoped queries)
        trace_ids: List of trace IDs to fetch summaries for
        batch_run_ids: Mapping of trace_id -> batch_run_id from the embeddings query
        window_start: Start of time window
        window_end: End of time window

    Returns:
        Dictionary mapping trace_id -> {title, flow_diagram, bullets, interesting_notes, trace_timestamp}
    """
    if not trace_ids:
        return {}

    # Use a high limit to handle duplicate summary events per trace (some traces have up to 4 summaries)
    # We'll filter by batch_run_id in Python after fetching
    max_rows = len(trace_ids) * 5  # Allow for duplicates

    query = parse_select(
        """
        SELECT
            coalesce(properties.$ai_trace_id, JSONExtractString(properties, '$ai_trace_id')) as trace_id,
            properties.$ai_summary_title as title,
            properties.$ai_summary_flow_diagram as flow_diagram,
            properties.$ai_summary_bullets as bullets,
            properties.$ai_summary_interesting_notes as interesting_notes,
            properties.trace_timestamp as trace_timestamp,
            properties.$ai_batch_run_id as batch_run_id
        FROM events
        WHERE event = {event_name}
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND coalesce(properties.$ai_trace_id, JSONExtractString(properties, '$ai_trace_id')) IN {trace_ids}
        LIMIT {max_rows}
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
                "max_rows": ast.Constant(value=max_rows),
            },
            team=team,
        )

    rows = result.results or []
    trace_summaries: TraceSummaries = {}
    skipped_wrong_batch = 0

    for row in rows:
        trace_id = row[0]
        summary_batch_run_id = row[6]  # $ai_batch_run_id from summary event

        # Backwards compatibility: only filter if BOTH embedding and summary have batch_run_ids
        # - Old embeddings (rendering="llma_trace_detailed") won't have batch_run_id → accept any summary
        # - Old summaries won't have $ai_batch_run_id → accept them (can't verify match)
        # - New embeddings + new summaries → only accept if batch_run_ids match
        expected_batch_run_id = batch_run_ids.get(trace_id)
        if expected_batch_run_id and summary_batch_run_id and expected_batch_run_id != summary_batch_run_id:
            skipped_wrong_batch += 1
            continue

        # HogQL parses timestamp strings into datetime objects
        trace_ts = row[5]
        trace_ts_str = trace_ts.isoformat() if trace_ts else ""

        trace_summaries[trace_id] = {
            "title": row[1],
            "flow_diagram": row[2],
            "bullets": row[3],
            "interesting_notes": row[4],
            "trace_timestamp": trace_ts_str,
        }

    logger.debug(
        "fetch_trace_summaries_result",
        total_rows=len(rows),
        unique_trace_ids=len(trace_summaries),
        skipped_wrong_batch=skipped_wrong_batch,
    )

    return trace_summaries


def fetch_generation_embeddings_for_clustering(
    team: Team,
    window_start: datetime,
    window_end: datetime,
    max_samples: int,
    generation_filters: list[dict] | None = None,
) -> tuple[list[GenerationId], GenerationEmbeddings, GenerationBatchRunIds]:
    """Query generation IDs and embeddings from document_embeddings table using HogQL.

    Similar to fetch_trace_embeddings_for_clustering but for generation-level summaries.
    Uses the llm-generation-summary-detailed document type.

    Args:
        team: Team object to query embeddings for
        window_start: Start of time window
        window_end: End of time window
        max_samples: Maximum number of generations to sample
        generation_filters: Optional property filters to scope which generations are included

    Returns:
        Tuple of (list of generation IDs, dict mapping generation_id -> embedding vector,
                  dict mapping generation_id -> batch_run_id for linking to summaries)
    """
    # If filters provided, first get eligible generation IDs from events
    eligible_generation_ids: list[GenerationId] | None = None
    if generation_filters:
        eligible_generation_ids = _fetch_eligible_generation_ids(
            team=team,
            window_start=window_start,
            window_end=window_end,
            generation_filters=generation_filters,
            max_samples=max_samples,
        )
        if not eligible_generation_ids:
            return [], {}, {}

    # Build query for generation embeddings
    if eligible_generation_ids:
        query = parse_select(
            """
            SELECT document_id, embedding, rendering
            FROM raw_document_embeddings
            WHERE timestamp >= {start_dt}
                AND timestamp < {end_dt}
                AND product = {product}
                AND document_type = {document_type}
                AND length(embedding) > 0
                AND document_id IN {eligible_ids}
            ORDER BY rand()
            LIMIT {max_samples}
            """
        )
        eligible_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=gid) for gid in eligible_generation_ids])
    else:
        query = parse_select(
            """
            SELECT document_id, embedding, rendering
            FROM raw_document_embeddings
            WHERE timestamp >= {start_dt}
                AND timestamp < {end_dt}
                AND product = {product}
                AND document_type = {document_type}
                AND length(embedding) > 0
            ORDER BY rand()
            LIMIT {max_samples}
            """
        )
        eligible_ids_tuple = None

    placeholders: dict[str, ast.Expr] = {
        "start_dt": ast.Constant(value=window_start),
        "end_dt": ast.Constant(value=window_end),
        "product": ast.Constant(value=constants.LLMA_TRACE_PRODUCT),
        "document_type": ast.Constant(value=constants.LLMA_GENERATION_DOCUMENT_TYPE),
        "max_samples": ast.Constant(value=max_samples),
    }
    if eligible_ids_tuple:
        placeholders["eligible_ids"] = eligible_ids_tuple

    with tags_context(product=Product.LLM_ANALYTICS):
        result = execute_hogql_query(
            query_type="GenerationEmbeddingsForClustering",
            query=query,
            placeholders=placeholders,
            team=team,
        )

    rows = result.results or []

    logger.debug(
        "fetch_generation_embeddings_for_clustering_result",
        num_rows=len(rows),
    )

    # Build all maps
    generation_ids: list[GenerationId] = []
    embeddings_map: GenerationEmbeddings = {}
    batch_run_ids_map: GenerationBatchRunIds = {}

    for row in rows:
        generation_id = row[0]
        generation_ids.append(generation_id)
        embeddings_map[generation_id] = row[1]

        # Store batch_run_id from rendering field
        rendering_value = row[2]
        if rendering_value:
            batch_run_ids_map[generation_id] = rendering_value

    return generation_ids, embeddings_map, batch_run_ids_map


def _fetch_eligible_generation_ids(
    team: Team,
    window_start: datetime,
    window_end: datetime,
    generation_filters: list[dict],
    max_samples: int,
) -> list[GenerationId]:
    """Query generation event UUIDs that match the given property filters.

    Args:
        team: Team object
        window_start: Start of time window
        window_end: End of time window
        generation_filters: List of property filter dicts
        max_samples: Maximum number of generations to return

    Returns:
        List of generation event UUIDs matching the filter criteria
    """
    if not generation_filters:
        return []

    # Build property filter expression
    property_exprs: list[ast.Expr] = []
    for prop in generation_filters:
        property_exprs.append(property_to_expr(prop, team))

    property_filter_expr = ast.And(exprs=property_exprs) if len(property_exprs) > 1 else property_exprs[0]

    query = parse_select(
        """
        SELECT toString(uuid) as generation_id
        FROM events
        WHERE event = '$ai_generation'
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND {property_filters}
        ORDER BY rand()
        LIMIT {max_samples}
        """
    )

    with tags_context(product=Product.LLM_ANALYTICS):
        result = execute_hogql_query(
            query_type="EligibleGenerationIdsForClustering",
            query=query,
            placeholders={
                "start_dt": ast.Constant(value=window_start),
                "end_dt": ast.Constant(value=window_end),
                "property_filters": property_filter_expr,
                "max_samples": ast.Constant(value=max_samples * 2),  # Oversample
            },
            team=team,
        )

    rows = result.results or []
    return [row[0] for row in rows if row[0]]


def fetch_generation_summaries(
    team: Team,
    generation_ids: list[GenerationId],
    batch_run_ids: GenerationBatchRunIds,
    window_start: datetime,
    window_end: datetime,
) -> TraceSummaries:
    """Fetch generation summaries from $ai_generation_summary events using HogQL.

    Similar to fetch_trace_summaries but for generation-level summaries.

    Args:
        team: Team object (for HogQL team-scoped queries)
        generation_ids: List of generation event UUIDs to fetch summaries for
        batch_run_ids: Mapping of generation_id -> batch_run_id from embeddings query
        window_start: Start of time window
        window_end: End of time window

    Returns:
        Dictionary mapping generation_id -> {title, flow_diagram, bullets, interesting_notes, generation_timestamp}
    """
    if not generation_ids:
        return {}

    max_rows = len(generation_ids) * 5  # Allow for duplicates

    query = parse_select(
        """
        SELECT
            properties.$ai_generation_id as generation_id,
            properties.$ai_summary_title as title,
            properties.$ai_summary_flow_diagram as flow_diagram,
            properties.$ai_summary_bullets as bullets,
            properties.$ai_summary_interesting_notes as interesting_notes,
            properties.generation_timestamp as generation_timestamp,
            properties.$ai_batch_run_id as batch_run_id
        FROM events
        WHERE event = {event_name}
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND properties.$ai_generation_id IN {generation_ids}
        LIMIT {max_rows}
        """
    )

    generation_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=gid) for gid in generation_ids])

    with tags_context(product=Product.LLM_ANALYTICS):
        result = execute_hogql_query(
            query_type="GenerationSummariesForClustering",
            query=query,
            placeholders={
                "event_name": ast.Constant(value="$ai_generation_summary"),
                "start_dt": ast.Constant(value=window_start),
                "end_dt": ast.Constant(value=window_end),
                "generation_ids": generation_ids_tuple,
                "max_rows": ast.Constant(value=max_rows),
            },
            team=team,
        )

    rows = result.results or []
    generation_summaries: TraceSummaries = {}
    skipped_wrong_batch = 0

    for row in rows:
        generation_id = row[0]
        summary_batch_run_id = row[6]

        expected_batch_run_id = batch_run_ids.get(generation_id)
        if expected_batch_run_id and summary_batch_run_id and expected_batch_run_id != summary_batch_run_id:
            skipped_wrong_batch += 1
            continue

        gen_ts = row[5]
        gen_ts_str = gen_ts.isoformat() if gen_ts else ""

        generation_summaries[generation_id] = {
            "title": row[1],
            "flow_diagram": row[2],
            "bullets": row[3],
            "interesting_notes": row[4],
            "trace_timestamp": gen_ts_str,  # Reusing trace_timestamp key for compatibility
        }

    logger.debug(
        "fetch_generation_summaries_result",
        total_rows=len(rows),
        unique_generation_ids=len(generation_summaries),
        skipped_wrong_batch=skipped_wrong_batch,
    )

    return generation_summaries


def fetch_embeddings_for_clustering(
    team: Team,
    window_start: datetime,
    window_end: datetime,
    max_samples: int,
    analysis_level: AnalysisLevel = AnalysisLevel.TRACE,
    filters: list[dict] | None = None,
) -> tuple[list[str], dict[str, list[float]], dict[str, str]]:
    """Unified function to fetch embeddings for clustering.

    Dispatches to either trace-level or generation-level fetching based on analysis_level.

    Args:
        team: Team object
        window_start: Start of time window
        window_end: End of time window
        max_samples: Maximum number of items to sample
        analysis_level: Whether to fetch trace or generation embeddings
        filters: Optional property filters

    Returns:
        Tuple of (list of item IDs, embeddings map, batch_run_ids map)
    """
    if analysis_level == AnalysisLevel.GENERATION:
        return fetch_generation_embeddings_for_clustering(
            team=team,
            window_start=window_start,
            window_end=window_end,
            max_samples=max_samples,
            generation_filters=filters,
        )
    else:
        return fetch_trace_embeddings_for_clustering(
            team=team,
            window_start=window_start,
            window_end=window_end,
            max_samples=max_samples,
            trace_filters=filters,
        )


def fetch_summaries_for_clustering(
    team: Team,
    item_ids: list[str],
    batch_run_ids: dict[str, str],
    window_start: datetime,
    window_end: datetime,
    analysis_level: AnalysisLevel = AnalysisLevel.TRACE,
) -> TraceSummaries:
    """Unified function to fetch summaries for clustering.

    Dispatches to either trace-level or generation-level fetching based on analysis_level.

    Args:
        team: Team object
        item_ids: List of item IDs (trace IDs or generation IDs)
        batch_run_ids: Mapping of item_id -> batch_run_id
        window_start: Start of time window
        window_end: End of time window
        analysis_level: Whether to fetch trace or generation summaries

    Returns:
        Dictionary mapping item_id -> summary data
    """
    if analysis_level == AnalysisLevel.GENERATION:
        return fetch_generation_summaries(
            team=team,
            generation_ids=item_ids,
            batch_run_ids=batch_run_ids,
            window_start=window_start,
            window_end=window_end,
        )
    else:
        return fetch_trace_summaries(
            team=team,
            trace_ids=item_ids,
            batch_run_ids=batch_run_ids,
            window_start=window_start,
            window_end=window_end,
        )
