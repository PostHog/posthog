"""Activity for querying trace IDs from a time window."""

from datetime import UTC, datetime, timedelta

import structlog
import temporalio

from posthog.schema import DateRange, TracesQuery

from posthog.hogql_queries.ai.traces_query_runner import TracesQueryRunner
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def query_traces_in_window_activity(inputs: BatchSummarizationInputs) -> list[str]:
    """
    Query trace IDs from a time window using TracesQueryRunner.

    Queries up to max_traces from the specified time window (or last N minutes if not specified).
    Returns a list of trace IDs in random order for sampling.
    """

    def _execute_traces_query(date_from: str, date_to: str) -> list[str]:
        team = Team.objects.get(id=inputs.team_id)

        query = TracesQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            limit=inputs.max_traces,
            randomOrder=True,
        )

        runner = TracesQueryRunner(team=team, query=query)
        response = runner.calculate()

        return [trace.id for trace in response.results]

    if inputs.window_start and inputs.window_end:
        date_from = inputs.window_start
        date_to = inputs.window_end
    else:
        now = datetime.now(UTC)
        date_to = now.isoformat()
        date_from = (now - timedelta(minutes=inputs.window_minutes)).isoformat()

    trace_ids = await database_sync_to_async(_execute_traces_query, thread_sensitive=False)(date_from, date_to)

    return trace_ids
