"""Activity for sampling traces/generations from a time window.

Uses lightweight HogQL queries to sample trace IDs and timestamps.
The full trace data is fetched later by the summarization activity using
TraceQueryRunner per-item, so sampling only needs IDs and timestamps.
"""

import structlog
import temporalio

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.llm_analytics.trace_summarization.constants import (
    MAX_TRACE_EVENTS_LIMIT,
    MAX_TRACE_PROPERTIES_SIZE,
)
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs, SampledItem
from posthog.temporal.llm_analytics.trace_summarization.utils import format_datetime_for_clickhouse

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def sample_items_in_window_activity(inputs: BatchSummarizationInputs) -> list[SampledItem]:
    """
    Sample traces or generations from a time window using lightweight queries.

    For trace-level (analysis_level="trace"):
        Returns one SampledItem per trace with generation_id=None.

    For generation-level (analysis_level="generation"):
        Directly samples the last generation per trace, returning one SampledItem
        per generation with the parent trace's first_timestamp for navigation.

    Requires window_start and window_end to be set on inputs (computed by workflow
    using deterministic workflow time to avoid race conditions between runs).
    """
    if not inputs.window_start or not inputs.window_end:
        raise ValueError("window_start and window_end must be provided by the workflow")

    def _sample_items(
        team_id: int, window_start: str, window_end: str, max_items: int, analysis_level: str
    ) -> list[SampledItem]:
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            logger.info("Team not found in local database, skipping", team_id=team_id)
            return []

        start_dt_str = format_datetime_for_clickhouse(window_start)
        end_dt_str = format_datetime_for_clickhouse(window_end)

        if analysis_level == "generation":
            # Sample generations directly: get the last generation per trace
            # with the trace's first_timestamp for navigation.
            # We query all AI event types to get accurate trace_first_timestamp,
            # but use argMaxIf to only pick generation UUIDs.
            # Also filters by event count and total properties size to prevent
            # oversized traces from reaching the CPU-intensive formatting activity.
            generations_query = parse_select(
                """
                SELECT
                    properties.$ai_trace_id as trace_id,
                    argMaxIf(uuid, timestamp, event = '$ai_generation') as last_generation_id,
                    min(timestamp) as trace_first_timestamp,
                    count() as event_count,
                    sum(length(properties)) as total_properties_size
                FROM events
                WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
                    AND timestamp >= toDateTime({start_ts}, 'UTC')
                    AND timestamp < toDateTime({end_ts}, 'UTC')
                    AND properties.$ai_trace_id != ''
                GROUP BY trace_id
                HAVING last_generation_id IS NOT NULL
                    AND event_count <= {max_events}
                    AND total_properties_size <= {max_properties_size}
                ORDER BY trace_first_timestamp DESC
                LIMIT {limit}
                """
            )

            result = execute_hogql_query(
                query_type="GenerationsForSampling",
                query=generations_query,
                placeholders={
                    "start_ts": ast.Constant(value=start_dt_str),
                    "end_ts": ast.Constant(value=end_dt_str),
                    "limit": ast.Constant(value=max_items),
                    "max_events": ast.Constant(value=MAX_TRACE_EVENTS_LIMIT),
                    "max_properties_size": ast.Constant(value=MAX_TRACE_PROPERTIES_SIZE),
                },
                team=team,
                limit_context=LimitContext.QUERY_ASYNC,
            )

            logger.debug(
                "generation_sampling_result",
                num_generations=len(result.results or []),
                start_ts=start_dt_str,
                end_ts=end_dt_str,
                team_id=team_id,
                max_events_filter=MAX_TRACE_EVENTS_LIMIT,
                max_properties_size_filter=MAX_TRACE_PROPERTIES_SIZE,
            )

            items: list[SampledItem] = []
            for row in result.results or []:
                trace_id = row[0]
                generation_id = row[1]
                trace_first_timestamp = row[2]
                if trace_id and generation_id:
                    items.append(
                        SampledItem(
                            trace_id=trace_id,
                            trace_first_timestamp=str(trace_first_timestamp),
                            generation_id=str(generation_id),
                        )
                    )

            return items
        else:
            # Trace-level: sample trace IDs and first timestamps.
            # Filters out traces with more than MAX_TRACE_EVENTS_LIMIT events
            # AND traces where total properties size exceeds MAX_TRACE_PROPERTIES_SIZE
            # to prevent CPU-intensive formatting from blocking the worker.
            traces_query = parse_select(
                """
                SELECT
                    properties.$ai_trace_id as trace_id,
                    min(timestamp) as first_timestamp,
                    count() as event_count,
                    sum(length(properties)) as total_properties_size
                FROM events
                WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
                    AND timestamp >= toDateTime({start_ts}, 'UTC')
                    AND timestamp < toDateTime({end_ts}, 'UTC')
                    AND properties.$ai_trace_id != ''
                GROUP BY trace_id
                HAVING event_count <= {max_events}
                    AND total_properties_size <= {max_properties_size}
                ORDER BY first_timestamp DESC
                LIMIT {limit}
                """
            )

            result = execute_hogql_query(
                query_type="TracesForSampling",
                query=traces_query,
                placeholders={
                    "start_ts": ast.Constant(value=start_dt_str),
                    "end_ts": ast.Constant(value=end_dt_str),
                    "limit": ast.Constant(value=max_items),
                    "max_events": ast.Constant(value=MAX_TRACE_EVENTS_LIMIT),
                    "max_properties_size": ast.Constant(value=MAX_TRACE_PROPERTIES_SIZE),
                },
                team=team,
                limit_context=LimitContext.QUERY_ASYNC,
            )

            logger.debug(
                "trace_sampling_result",
                num_traces=len(result.results or []),
                start_ts=start_dt_str,
                end_ts=end_dt_str,
                team_id=team_id,
                max_events_filter=MAX_TRACE_EVENTS_LIMIT,
                max_properties_size_filter=MAX_TRACE_PROPERTIES_SIZE,
            )

            return [
                SampledItem(
                    trace_id=row[0],
                    trace_first_timestamp=str(row[1]),
                    generation_id=None,
                )
                for row in (result.results or [])
                if row[0]
            ]

    async with Heartbeater():
        items = await database_sync_to_async(_sample_items, thread_sensitive=False)(
            inputs.team_id,
            inputs.window_start,
            inputs.window_end,
            inputs.max_items,
            inputs.analysis_level,
        )

    logger.debug(
        "sample_items_in_window_result",
        num_items=len(items),
        analysis_level=inputs.analysis_level,
        team_id=inputs.team_id,
    )

    return items
