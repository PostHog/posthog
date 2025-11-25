"""Data access layer for trace clustering.

This module consolidates all ClickHouse queries used by the clustering workflow,
providing a single source of truth for data fetching operations.
"""

from datetime import datetime

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.models import TraceEmbeddings, TraceId, TraceSummaries


def fetch_trace_ids_for_clustering(
    team_id: int,
    window_start: datetime,
    window_end: datetime,
    max_samples: int | None = None,
    random_seed: int = 42,
) -> list[TraceId]:
    """Query and sample trace IDs from document_embeddings table.

    Args:
        team_id: Team ID to query embeddings for
        window_start: Start of time window
        window_end: End of time window
        max_samples: Maximum number of traces to sample (None = all traces)

    Returns:
        List of trace IDs (strings)
    """
    query = """
        SELECT document_id as trace_id
        FROM posthog_document_embeddings
        WHERE team_id = %(team_id)s
            AND timestamp >= %(start_dt)s
            AND timestamp < %(end_dt)s
            AND rendering IN (%(minimal_rendering)s, %(detailed_rendering)s)
            AND length(embedding) > 0
    """
    params = {
        "team_id": team_id,
        "start_dt": window_start,
        "end_dt": window_end,
        "minimal_rendering": constants.LLMA_TRACE_MINIMAL_RENDERING,
        "detailed_rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
    }

    if max_samples and max_samples > 0:
        query += """
            ORDER BY rand()
            LIMIT %(max_samples)s
        """
        params["max_samples"] = max_samples

    results = sync_execute(query, params, workload=Workload.OFFLINE)
    trace_ids = [row[0] for row in results]

    return trace_ids


def fetch_embeddings_by_trace_ids(
    team_id: int,
    trace_ids: list[TraceId],
    window_start: datetime,
    window_end: datetime,
) -> TraceEmbeddings:
    """Fetch embeddings for given trace IDs from document_embeddings table.

    Args:
        team_id: Team ID (for security/filtering)
        trace_ids: List of trace IDs to fetch embeddings for

    Returns:
        Dictionary mapping trace_id -> embedding vector
    """

    query = """
        SELECT document_id, embedding
        FROM posthog_document_embeddings
        WHERE team_id = %(team_id)s
            AND timestamp >= %(start_dt)s
            AND timestamp < %(end_dt)s
            AND document_id IN %(trace_ids)s
            AND rendering IN (%(minimal_rendering)s, %(detailed_rendering)s)
            AND length(embedding) > 0
    """
    params = {
        "team_id": team_id,
        "start_dt": window_start,
        "end_dt": window_end,
        "trace_ids": trace_ids,
        "minimal_rendering": constants.LLMA_TRACE_MINIMAL_RENDERING,
        "detailed_rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
    }

    results = sync_execute(query, params, workload=Workload.OFFLINE)

    # Build mapping: trace_id -> embedding
    embedding_map = {row[0]: row[1] for row in results}

    return embedding_map


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

    results = sync_execute(
        query,
        {
            "team_id": team_id,
            "trace_ids": trace_ids,
            "start_dt": window_start,
            "end_dt": window_end,
        },
        workload=Workload.OFFLINE,
    )

    trace_summaries = {
        row[0]: {
            "title": row[1],
            "flow_diagram": row[2],
            "bullets": row[3],
            "interesting_notes": row[4],
        }
        for row in results
    }

    return trace_summaries
