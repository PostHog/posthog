"""Activity for fetching full trace data and hierarchy."""

from datetime import datetime, timedelta
from typing import Any

import temporalio

from posthog.schema import DateRange, TraceQuery

from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner
from posthog.models.team import Team
from posthog.sync import database_sync_to_async


@temporalio.activity.defn
async def fetch_trace_hierarchy_activity(trace_id: str, team_id: int, timestamp: str) -> dict[str, Any]:
    """
    Fetch full trace using TraceQueryRunner.

    Uses the existing TraceQueryRunner to get the trace and all its events.
    Returns trace metadata and hierarchy suitable for text repr formatting.
    """

    def _execute_trace_query():
        # Get team object
        team = Team.objects.get(id=team_id)

        # Parse timestamp to create date range
        # Use a window around the timestamp to ensure we capture the trace
        trace_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        date_from = (trace_time - timedelta(minutes=15)).isoformat()
        date_to = (trace_time + timedelta(minutes=15)).isoformat()

        # Build query using TraceQueryRunner
        query = TraceQuery(
            traceId=trace_id,
            dateRange=DateRange(date_from=date_from, date_to=date_to),
        )

        # Execute query
        runner = TraceQueryRunner(team=team, query=query)
        response = runner.calculate()

        if not response.results:
            raise ValueError(f"No events found for trace {trace_id}")

        # Get the trace data (first result)
        llm_trace = response.results[0]

        # Convert LLMTrace to format_trace_text_repr format
        trace_dict = {
            "id": llm_trace.id,
            "properties": {
                "$ai_trace_id": llm_trace.id,
                "$ai_span_name": llm_trace.traceName,
                "$ai_session_id": llm_trace.aiSessionId,
                "$ai_input_state": llm_trace.inputState,
                "$ai_output_state": llm_trace.outputState,
            },
        }

        # Convert events to hierarchy format (flat list with empty children)
        hierarchy = [
            {
                "event": {
                    "id": event.id,
                    "event": event.event,
                    "properties": event.properties,
                    "timestamp": event.createdAt,
                },
                "children": [],
            }
            for event in llm_trace.events
        ]

        return {"trace": trace_dict, "hierarchy": hierarchy}

    # Execute the query (wrapped for async)
    return await database_sync_to_async(_execute_trace_query, thread_sensitive=False)()
