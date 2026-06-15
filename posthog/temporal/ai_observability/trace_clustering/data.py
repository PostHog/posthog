"""Data access layer for trace clustering.

This module consolidates all HogQL queries used by the clustering workflow,
providing a single source of truth for data fetching operations.
All queries are team-scoped through HogQL's automatic team filtering.
"""

from dataclasses import dataclass
from datetime import datetime

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.temporal.ai_observability.trace_clustering import constants
from posthog.temporal.ai_observability.trace_clustering.models import (
    AnalysisLevel,
    ItemBatchRunIds,
    ItemEmbeddings,
    ItemId,
    ItemSummaries,
)

from products.ai_observability.backend.summarization.models import SummarizationMode

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
    """Query item IDs and embeddings from the document_embeddings table.

    Two paths:

    - **job_id present** — scope to one ClusteringJob via its durable summary events
      (``$ai_clustering_job_id``), then read the shared per-item embeddings by ``document_id``.
      The embeddings' own ``metadata.job_id`` is deliberately *not* used for scoping: the table
      is a ReplacingMergeTree keyed on ``(team_id, toDate(timestamp), product, document_type,
      rendering, cityHash64(document_id))``, so when two jobs summarize the same item on the same
      day in the same mode their rows share a key and collapse on merge — only one job's
      ``metadata.job_id`` survives, and the other job would silently lose those embeddings. The
      summary events are written one-per-job-run and never collapse, so each job recovers its
      own complete sample regardless of overlap.
    - **no job_id** — return all embeddings for the document type (legacy/unfiltered), pairing
      each embedding to its summary via ``batch_run_id`` (metadata, falling back to the
      pre-migration ``rendering`` form). The fallback can be dropped once the table's 3-month TTL
      has cycled out all pre-migration rows.
    """
    document_type = (
        constants.LLMA_GENERATION_DOCUMENT_TYPE
        if analysis_level == "generation"
        else constants.LLMA_TRACE_DOCUMENT_TYPE
    )

    if job_id:
        return _fetch_job_scoped_embeddings(
            team=team,
            job_id=job_id,
            window_start=window_start,
            window_end=window_end,
            max_samples=max_samples,
            analysis_level=analysis_level,
            document_type=document_type,
        )

    # Legacy/unfiltered path (no clustering job): all embeddings for the document type in-window.
    query = parse_select(
        """
        SELECT document_id, embedding, rendering, JSONExtractString(metadata, 'batch_run_id') AS meta_batch_run_id
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
        "document_type_legacy": ast.Constant(value=constants.LLMA_TRACE_DOCUMENT_TYPE_LEGACY),
        "rendering_legacy": ast.Constant(value=constants.LLMA_TRACE_RENDERING_LEGACY),
        "max_samples": ast.Constant(value=max_samples),
    }

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
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

    # `rendering` values that are NOT batch_run_ids: the current summary-mode enum plus the older
    # legacy render modes. A row whose rendering is one of these and whose metadata lacks a
    # batch_run_id contributes no pairing key, so fetch_item_summaries accepts any matching summary.
    non_batch_run_id_renderings = {
        constants.LLMA_TRACE_RENDERING_LEGACY,  # "llma_trace_detailed"
        "llma_trace_minimal",  # legacy minimal rendering
        *(mode.value for mode in SummarizationMode),  # current rendering values
    }

    for row in rows:
        item_id = row[0]
        item_ids.append(item_id)
        embeddings_map[item_id] = row[1]

        # batch_run_id now lives in metadata; prefer it. Pre-migration rows carry it in
        # `rendering` instead (rendering = batch_run_id, e.g. "1_2025-12-13T..._job"), so fall
        # back to rendering when it isn't one of the known mode values.
        rendering_value = row[2]
        meta_batch_run_id = row[3]
        if meta_batch_run_id:
            batch_run_ids_map[item_id] = meta_batch_run_id
        elif rendering_value and rendering_value not in non_batch_run_id_renderings:
            batch_run_ids_map[item_id] = rendering_value

    return item_ids, embeddings_map, batch_run_ids_map


def _fetch_job_scoped_item_ids(
    team: Team,
    job_id: str,
    window_start: datetime,
    window_end: datetime,
    max_samples: int,
    analysis_level: AnalysisLevel,
) -> list[ItemId]:
    """Item ids a clustering job summarized in-window, read from its durable summary events.

    ``$ai_trace_summary`` / ``$ai_generation_summary`` events carry ``$ai_clustering_job_id`` and
    are written one-per-job-run, so they never collapse the way the embeddings ReplacingMergeTree
    rows do — two jobs that sampled the same item each recover their own complete scope.
    Random-sampled to ``max_samples`` to bound the downstream embedding read.
    """
    event_name = "$ai_generation_summary" if analysis_level == "generation" else "$ai_trace_summary"
    id_property = "$ai_generation_id" if analysis_level == "generation" else "$ai_trace_id"

    # ast.Field placeholders so HogQL resolves materialized columns instead of JSONExtract.
    query = parse_select(
        """
        SELECT {id_prop} AS item_id
        FROM events
        WHERE event = {event_name}
            AND timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND {job_id_prop} = {job_id}
        GROUP BY item_id
        ORDER BY rand()
        LIMIT {max_samples}
        """
    )

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        result = execute_hogql_query(
            query_type="JobScopedItemIdsForClustering",
            query=query,
            placeholders={
                "id_prop": ast.Field(chain=["properties", id_property]),
                "event_name": ast.Constant(value=event_name),
                "start_dt": ast.Constant(value=window_start),
                "end_dt": ast.Constant(value=window_end),
                "job_id_prop": ast.Field(chain=["properties", "$ai_clustering_job_id"]),
                "job_id": ast.Constant(value=job_id),
                "max_samples": ast.Constant(value=max_samples),
            },
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=CLUSTERING_QUERY_MAX_EXECUTION_TIME),
        )

    rows = result.results or []
    return [row[0] for row in rows if row[0]]


def _fetch_job_scoped_embeddings(
    team: Team,
    job_id: str,
    window_start: datetime,
    window_end: datetime,
    max_samples: int,
    analysis_level: AnalysisLevel,
    document_type: str,
) -> tuple[list[ItemId], ItemEmbeddings, ItemBatchRunIds]:
    """Embeddings for the items a clustering job summarized, scoped via its summary events.

    Embeddings are shared per ``(item, mode)`` and read by ``document_id``, so overlapping jobs
    reuse the same row without collision. ``batch_run_ids`` comes back empty: pairing is by
    ``item_id`` downstream (fetch_item_summaries accepts any matching summary when no batch_run_id
    is supplied), since there is no per-job embedding row to match against.
    """
    item_ids = _fetch_job_scoped_item_ids(
        team=team,
        job_id=job_id,
        window_start=window_start,
        window_end=window_end,
        max_samples=max_samples,
        analysis_level=analysis_level,
    )
    if not item_ids:
        logger.info(
            "fetch_item_embeddings_for_clustering_result",
            num_rows=0,
            num_items=0,
            analysis_level=analysis_level,
            job_id=job_id,
        )
        return [], {}, {}

    query = parse_select(
        """
        SELECT document_id, embedding
        FROM raw_document_embeddings
        WHERE timestamp >= {start_dt}
            AND timestamp < {end_dt}
            AND product = {product}
            AND document_type = {document_type}
            AND document_id IN {item_ids}
            AND length(embedding) > 0
        """
    )
    item_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=iid) for iid in item_ids])

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        result = execute_hogql_query(
            query_type="ItemEmbeddingsForClustering",
            query=query,
            placeholders={
                "start_dt": ast.Constant(value=window_start),
                "end_dt": ast.Constant(value=window_end),
                "product": ast.Constant(value=constants.LLMA_TRACE_PRODUCT),
                "document_type": ast.Constant(value=document_type),
                "item_ids": item_ids_tuple,
            },
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=CLUSTERING_QUERY_MAX_EXECUTION_TIME),
        )

    rows = result.results or []
    # Dedupe on document_id: pre-merge the table can briefly hold one row per job for the same
    # item, but the embedding content is identical, so either row is fine.
    embeddings_map: ItemEmbeddings = {row[0]: row[1] for row in rows}
    scoped_item_ids: list[ItemId] = list(embeddings_map.keys())

    logger.info(
        "fetch_item_embeddings_for_clustering_result",
        num_rows=len(rows),
        num_items=len(scoped_item_ids),
        analysis_level=analysis_level,
        job_id=job_id,
    )
    return scoped_item_ids, embeddings_map, {}


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

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
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


@dataclass(frozen=True)
class ItemMetrics:
    """Per-item operational metrics from AI events."""

    cost: float | None
    latency: float | None
    input_tokens: int | None
    output_tokens: int | None
    error_count: int


def fetch_item_metrics(
    team: Team,
    item_ids: list[str],
    window_start: datetime,
    window_end: datetime,
    analysis_level: AnalysisLevel = "trace",
) -> dict[str, ItemMetrics]:
    """Fetch cost, latency, tokens, and error counts for clustered items.

    For trace-level: aggregates across all AI events in each trace.
    For generation-level: fetches metrics from individual $ai_generation events.
    """
    if not item_ids:
        return {}

    is_generation = analysis_level == "generation"

    if is_generation:
        # Cast constant IDs to UUID to filter on native uuid column (avoids per-row toString)
        item_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=iid) for iid in item_ids])
        query = parse_select(
            """
            SELECT
                toString(uuid) as item_id,
                toFloat(properties.$ai_total_cost_usd) as cost,
                toFloat(properties.$ai_latency) as latency,
                toInt(properties.$ai_input_tokens) as input_tokens,
                toInt(properties.$ai_output_tokens) as output_tokens,
                if(properties.$ai_is_error = 'true', 1, 0) as error_count
            FROM events
            WHERE event = '$ai_generation'
                AND timestamp >= {start_dt}
                AND timestamp < {end_dt}
                AND uuid IN {item_ids}
            LIMIT {max_rows}
            """
        )
    else:
        # Use ast.Field placeholder so HogQL resolves materialized columns for $ai_trace_id
        # (JSONExtractString would bypass materialized column optimization)
        item_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=iid) for iid in item_ids])
        query = parse_select(
            """
            SELECT
                {trace_id_prop} as item_id,
                sumIf(toFloat(properties.$ai_total_cost_usd), event IN ('$ai_generation', '$ai_embedding')) as cost,
                sumIf(toFloat(properties.$ai_latency), event = '$ai_generation') as latency,
                sumIf(toInt(properties.$ai_input_tokens), event IN ('$ai_generation', '$ai_embedding')) as input_tokens,
                sumIf(toInt(properties.$ai_output_tokens), event IN ('$ai_generation', '$ai_embedding')) as output_tokens,
                countIf(properties.$ai_is_error = 'true') as error_count
            FROM events
            WHERE event IN ('$ai_generation', '$ai_embedding', '$ai_span')
                AND timestamp >= {start_dt}
                AND timestamp < {end_dt}
                AND {trace_id_prop} IN {item_ids}
            GROUP BY item_id
            LIMIT {max_rows}
            """
        )

    placeholders: dict[str, ast.Expr] = {
        "start_dt": ast.Constant(value=window_start),
        "end_dt": ast.Constant(value=window_end),
        "item_ids": item_ids_tuple,
        "max_rows": ast.Constant(value=len(item_ids)),
    }
    if not is_generation:
        placeholders["trace_id_prop"] = ast.Field(chain=["properties", "$ai_trace_id"])

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        result = execute_hogql_query(
            query_type="ClusterItemMetrics",
            query=query,
            placeholders=placeholders,
            team=team,
            settings=HogQLGlobalSettings(max_execution_time=CLUSTERING_QUERY_MAX_EXECUTION_TIME),
        )

    metrics: dict[str, ItemMetrics] = {}
    for row in result.results or []:
        item_id = row[0]
        if item_id:
            metrics[item_id] = ItemMetrics(
                cost=row[1],
                latency=row[2],
                input_tokens=row[3],
                output_tokens=row[4],
                error_count=int(row[5] or 0),
            )

    logger.info(
        "fetch_item_metrics_result",
        item_count=len(metrics),
        requested=len(item_ids),
        analysis_level=analysis_level,
    )

    return metrics
