"""Activity for querying generation IDs from a time window."""

from datetime import datetime

import structlog
import temporalio

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs

logger = structlog.get_logger(__name__)


def _format_datetime_for_clickhouse(iso_string: str) -> str:
    """Convert ISO format datetime string to ClickHouse-compatible format."""
    dt = datetime.fromisoformat(iso_string)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@temporalio.activity.defn
async def query_generations_in_window_activity(inputs: BatchSummarizationInputs) -> list[tuple[str, str]]:
    """
    Query generation IDs and their parent trace IDs from a time window.

    Queries $ai_generation events directly from the events table.
    Returns a list of (generation_id, trace_id) tuples in random order for sampling.

    Requires window_start and window_end to be set on inputs (computed by workflow
    using deterministic workflow time to avoid race conditions between runs).
    """
    if not inputs.window_start or not inputs.window_end:
        raise ValueError("window_start and window_end must be provided by the workflow")

    def _execute_generations_query(
        team_id: int, window_start: str, window_end: str, max_items: int
    ) -> list[tuple[str, str]]:
        team = Team.objects.get(id=team_id)

        # Convert ISO format to ClickHouse-compatible format
        start_dt_str = _format_datetime_for_clickhouse(window_start)
        end_dt_str = _format_datetime_for_clickhouse(window_end)

        query = parse_select(
            """
            SELECT
                id as generation_id,
                properties.$ai_trace_id as trace_id
            FROM events
            WHERE event = '$ai_generation'
                AND timestamp >= toDateTime({start_dt})
                AND timestamp < toDateTime({end_dt})
                AND isNotNull(properties.$ai_trace_id)
                AND properties.$ai_trace_id != ''
            ORDER BY rand()
            LIMIT {max_items}
            """
        )

        result = execute_hogql_query(
            query_type="GenerationsInWindowForSummarization",
            query=query,
            placeholders={
                "start_dt": ast.Constant(value=start_dt_str),
                "end_dt": ast.Constant(value=end_dt_str),
                "max_items": ast.Constant(value=max_items),
            },
            team=team,
        )

        rows = result.results or []
        return [(row[0], row[1]) for row in rows if row[0] and row[1]]

    generation_tuples = await database_sync_to_async(_execute_generations_query, thread_sensitive=False)(
        inputs.team_id,
        inputs.window_start,
        inputs.window_end,
        inputs.max_items,
    )

    logger.debug(
        "query_generations_in_window_result",
        num_generations=len(generation_tuples),
        team_id=inputs.team_id,
    )

    return generation_tuples
