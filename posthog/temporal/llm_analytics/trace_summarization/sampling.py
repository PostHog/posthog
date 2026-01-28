"""Activity for sampling traces/generations from a time window.

Uses TracesQueryRunner for both trace-level and generation-level sampling.
For generation-level, samples traces first then queries for the last generation
per trace - this ensures each generation has its parent trace's first_timestamp
for navigation.
"""

import structlog
import temporalio

from posthog.schema import DateRange, TracesQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.ai.traces_query_runner import TracesQueryRunner
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs, SampledItem
from posthog.temporal.llm_analytics.trace_summarization.utils import format_datetime_for_clickhouse

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def sample_items_in_window_activity(inputs: BatchSummarizationInputs) -> list[SampledItem]:
    """
    Sample traces or generations from a time window using TracesQueryRunner.

    For trace-level (analysis_level="trace"):
        Returns one SampledItem per trace with generation_id=None.

    For generation-level (analysis_level="generation"):
        Samples traces first to get trace context (id, first_timestamp), then
        queries for the last $ai_generation event per trace.
        Returns one SampledItem per generation with the parent trace's context.

    This unified approach ensures both levels have access to the trace's
    first_timestamp, which is needed for navigation in the cluster scatter plot.

    Requires window_start and window_end to be set on inputs (computed by workflow
    using deterministic workflow time to avoid race conditions between runs).
    """
    if not inputs.window_start or not inputs.window_end:
        raise ValueError("window_start and window_end must be provided by the workflow")

    def _sample_items(
        team_id: int, window_start: str, window_end: str, max_items: int, analysis_level: str
    ) -> list[SampledItem]:
        team = Team.objects.get(id=team_id)

        # Step 1: Sample traces using TracesQueryRunner
        query = TracesQuery(
            dateRange=DateRange(date_from=window_start, date_to=window_end),
            limit=max_items,
            randomOrder=True,
        )

        runner = TracesQueryRunner(team=team, query=query)
        response = runner.calculate()

        logger.debug(
            "traces_query_runner_result",
            num_traces=len(response.results),
            analysis_level=analysis_level,
            window_start=window_start,
            window_end=window_end,
            team_id=team_id,
        )

        if analysis_level == "generation":
            # Step 2: For generation-level, query for last generation per trace
            trace_context = {trace.id: trace.createdAt for trace in response.results}

            if not trace_context:
                return []

            # Query last generation per trace (with timestamp bounds for efficiency)
            # Note: We use argMax(uuid, timestamp) to select only the LAST generation
            # per trace. This means only the most recent generation in each trace
            # gets summarized, which is intentional to avoid duplicate summaries
            # and focus on the final output of each trace.
            trace_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=tid) for tid in trace_context.keys()])

            # Convert ISO format to ClickHouse-compatible format
            start_dt_str = format_datetime_for_clickhouse(window_start)
            end_dt_str = format_datetime_for_clickhouse(window_end)

            generations_query = parse_select(
                """
                SELECT
                    properties.$ai_trace_id as trace_id,
                    argMax(uuid, timestamp) as last_generation_id
                FROM events
                WHERE event = '$ai_generation'
                    AND timestamp >= toDateTime({start_ts}, 'UTC')
                    AND timestamp < toDateTime({end_ts}, 'UTC')
                    AND properties.$ai_trace_id IN {trace_ids}
                GROUP BY trace_id
                """
            )

            result = execute_hogql_query(
                query_type="GenerationsForSampling",
                query=generations_query,
                placeholders={
                    "trace_ids": trace_ids_tuple,
                    "start_ts": ast.Constant(value=start_dt_str),
                    "end_ts": ast.Constant(value=end_dt_str),
                },
                team=team,
            )

            logger.debug(
                "generation_query_result",
                num_generations=len(result.results or []),
                num_trace_ids_queried=len(trace_context),
                start_ts=start_dt_str,
                end_ts=end_dt_str,
                team_id=team_id,
            )

            items: list[SampledItem] = []
            for row in result.results or []:
                trace_id = row[0]
                generation_id = row[1]
                if trace_id in trace_context:
                    items.append(
                        SampledItem(
                            trace_id=trace_id,
                            trace_first_timestamp=trace_context[trace_id],
                            generation_id=str(generation_id),
                        )
                    )

            return items
        else:
            # Trace-level: one item per trace
            return [
                SampledItem(
                    trace_id=trace.id,
                    trace_first_timestamp=trace.createdAt,
                    generation_id=None,
                )
                for trace in response.results
            ]

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
