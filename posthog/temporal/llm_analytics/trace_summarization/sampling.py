"""Activity for querying traces from a time window."""

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
import temporalio

from posthog.schema import DateRange, TracesQuery

from posthog.hogql_queries.ai.traces_query_runner import TracesQueryRunner
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def query_traces_in_window_activity(inputs: BatchSummarizationInputs) -> list[dict[str, Any]]:
    """
    Query traces from a time window using TracesQueryRunner.

    Queries up to max_traces from the specified time window (or last N minutes if not specified).
    Returns trace metadata (id, timestamp) ordered by timestamp DESC (most recent first).

    This approach is idempotent - rerunning on the same window will return the same traces.
    """
    if inputs.window_start and inputs.window_end:
        date_from = inputs.window_start
        date_to = inputs.window_end
    else:
        now = datetime.now(UTC)
        date_to = now.isoformat()
        date_from = (now - timedelta(minutes=inputs.window_minutes)).isoformat()

    def _execute_traces_query():
        team = Team.objects.get(id=inputs.team_id)

        query = TracesQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            limit=inputs.max_traces,
            randomOrder=True,
        )

        runner = TracesQueryRunner(team=team, query=query)
        response = runner.calculate()
        results = response.results

        trace_list = [
            {
                "trace_id": trace.id,
                "trace_timestamp": trace.createdAt,
                "team_id": inputs.team_id,
            }
            for trace in results
        ]

        return trace_list

    trace_list = await database_sync_to_async(_execute_traces_query, thread_sensitive=False)()

    return trace_list
