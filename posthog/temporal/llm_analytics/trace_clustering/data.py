"""Data access layer for trace clustering.

This module consolidates all ClickHouse queries used by the clustering workflow,
providing a single source of truth for data fetching operations.
"""

from datetime import datetime
from typing import Any

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.models import TraceEmbeddings, TraceId, TraceSummaries


def _rows_to_dicts(rows: list[tuple[Any, ...]], column_types: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Convert ClickHouse rows to dictionaries using column names.

    This provides safe column access by name rather than fragile index-based access.
    """
    column_names = [col[0] for col in column_types]
    return [dict(zip(column_names, row)) for row in rows]


def fetch_trace_embeddings_for_clustering(
    team_id: int,
    window_start: datetime,
    window_end: datetime,
    max_samples: int,
) -> tuple[list[TraceId], TraceEmbeddings]:
    """Query trace IDs and embeddings from document_embeddings table.

    Args:
        team_id: Team ID to query embeddings for
        window_start: Start of time window
        window_end: End of time window
        max_samples: Maximum number of traces to sample

    Returns:
        Tuple of (list of trace IDs, dict mapping trace_id -> embedding vector)
    """
    query = """
        SELECT document_id, embedding
        FROM posthog_document_embeddings
        WHERE team_id = %(team_id)s
            AND timestamp >= %(start_dt)s
            AND timestamp < %(end_dt)s
            AND product = %(product)s
            AND document_type = %(document_type)s
            AND rendering = %(rendering)s
            AND length(embedding) > 0
        ORDER BY rand()
        LIMIT %(max_samples)s
    """
    rows, column_types = sync_execute(
        query,
        {
            "team_id": team_id,
            "start_dt": window_start,
            "end_dt": window_end,
            "product": constants.LLMA_TRACE_PRODUCT,
            "document_type": constants.LLMA_TRACE_DOCUMENT_TYPE,
            "rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
            "max_samples": max_samples,
        },
        workload=Workload.OFFLINE,
        with_column_types=True,
    )

    results = _rows_to_dicts(rows, column_types)
    trace_ids = [row["document_id"] for row in results]
    embeddings_map = {row["document_id"]: row["embedding"] for row in results}

    return trace_ids, embeddings_map


def fetch_trace_summaries(
    team_id: int,
    trace_ids: list[TraceId],
    window_start: datetime,
    window_end: datetime,
) -> TraceSummaries:
    """Fetch trace summaries from $ai_trace_summary events.

    Args:
        team_id: Team ID (for security/filtering)
        trace_ids: List of trace IDs to fetch summaries for
        window_start: Start of time window
        window_end: End of time window

    Returns:
        Dictionary mapping trace_id -> {title, flow_diagram, bullets, interesting_notes}
    """

    query = """
        SELECT
            JSONExtractString(properties, '$ai_trace_id') as trace_id,
            JSONExtractString(properties, '$ai_summary_title') as title,
            JSONExtractString(properties, '$ai_summary_flow_diagram') as flow_diagram,
            JSONExtractString(properties, '$ai_summary_bullets') as bullets,
            JSONExtractString(properties, '$ai_summary_interesting_notes') as interesting_notes
        FROM events
        WHERE team_id = %(team_id)s
            AND event = '$ai_trace_summary'
            AND timestamp >= %(start_dt)s
            AND timestamp < %(end_dt)s
            AND JSONExtractString(properties, '$ai_trace_id') IN %(trace_ids)s
    """

    rows, column_types = sync_execute(
        query,
        {
            "team_id": team_id,
            "trace_ids": trace_ids,
            "start_dt": window_start,
            "end_dt": window_end,
        },
        workload=Workload.OFFLINE,
        with_column_types=True,
    )

    results = _rows_to_dicts(rows, column_types)
    trace_summaries: TraceSummaries = {
        row["trace_id"]: {
            "title": row["title"],
            "flow_diagram": row["flow_diagram"],
            "bullets": row["bullets"],
            "interesting_notes": row["interesting_notes"],
        }
        for row in results
    }

    return trace_summaries
