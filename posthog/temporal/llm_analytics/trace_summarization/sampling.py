"""Activity for querying trace IDs from a time window."""

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

    Queries up to max_traces from the specified time window.
    Returns a list of trace IDs in random order for sampling.

    Requires window_start and window_end to be set on inputs (computed by workflow
    using deterministic workflow time to avoid race conditions between runs).
    """
    if not inputs.window_start or not inputs.window_end:
        raise ValueError("window_start and window_end must be provided by the workflow")

    def _execute_traces_query(team_id: int, window_start: str, window_end: str, max_traces: int) -> list[str]:
        team = Team.objects.get(id=team_id)

        query = TracesQuery(
            dateRange=DateRange(date_from=window_start, date_to=window_end),
            limit=max_traces,
            randomOrder=True,
        )

        runner = TracesQueryRunner(team=team, query=query)
        response = runner.calculate()

        return [trace.id for trace in response.results]

    trace_ids = await database_sync_to_async(_execute_traces_query, thread_sensitive=False)(
        inputs.team_id,
        inputs.window_start,
        inputs.window_end,
        inputs.max_traces,
    )

    return trace_ids
