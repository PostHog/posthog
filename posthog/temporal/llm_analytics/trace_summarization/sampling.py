"""Activity for sampling traces from ClickHouse."""

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
import temporalio

from posthog.schema import DateRange, TracesQuery

from posthog.hogql_queries.ai.traces_query_runner import TracesQueryRunner
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.llm_analytics.trace_summarization.constants import MIN_SAMPLE_SIZE, SAMPLE_LOOKBACK_DAYS
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def sample_recent_traces_activity(inputs: BatchSummarizationInputs) -> list[dict[str, Any]]:
    """
    Sample N recent traces using TracesQueryRunner.

    Uses the existing TracesQueryRunner to get traces from the past SAMPLE_LOOKBACK_DAYS.
    Returns trace metadata (id, timestamp) for further processing.
    """
    # Determine date range
    if inputs.start_date and inputs.end_date:
        date_from = inputs.start_date
        date_to = inputs.end_date
    else:
        now = datetime.now(UTC)
        date_to = now.isoformat()
        date_from = (now - timedelta(days=SAMPLE_LOOKBACK_DAYS)).isoformat()

    # Use TracesQueryRunner to sample traces
    def _execute_traces_query():
        # Get team object
        team = Team.objects.get(id=inputs.team_id)

        # Build query using TracesQueryRunner
        query = TracesQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            limit=inputs.sample_size,
        )

        # Execute query
        runner = TracesQueryRunner(team=team, query=query)
        response = runner.calculate()

        # Extract trace metadata
        return [
            {
                "trace_id": trace.id,
                "trace_timestamp": trace.createdAt,
                "team_id": inputs.team_id,
            }
            for trace in response.results
        ]

    # Execute the query (wrapped for async)
    traces = await database_sync_to_async(_execute_traces_query, thread_sensitive=False)()

    # Validate minimum threshold
    if len(traces) < MIN_SAMPLE_SIZE:
        logger.warning(
            "Insufficient traces found",
            team_id=inputs.team_id,
            found=len(traces),
            min_required=MIN_SAMPLE_SIZE,
            date_from=date_from,
            date_to=date_to,
        )
        return []

    logger.info(
        "Trace sampling completed",
        team_id=inputs.team_id,
        sampled_count=len(traces),
        date_from=date_from,
        date_to=date_to,
    )

    return traces
