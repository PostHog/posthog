"""Activity for generating trace summaries using LLM."""

from typing import Any

import structlog
import temporalio

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def generate_and_save_summary_activity(
    trace_id: str,
    team_id: int,
    timestamp: str,
    mode: str,
    batch_run_id: str,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Generate summary for a trace and save it to ClickHouse.

    Fetches trace data, generates summary, and immediately saves it as an event.
    This avoids passing large TraceSummary objects through workflow history.

    Returns:
        Dict with trace_id, success status, and metadata
    """
    from datetime import datetime, timedelta
    from uuid import uuid4

    from posthog.schema import DateRange, TraceQuery

    from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner
    from posthog.models.team import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.llm_analytics.trace_summarization import constants

    from products.llm_analytics.backend.summarization.llm import summarize
    from products.llm_analytics.backend.text_repr.formatters import FormatterOptions, format_trace_text_repr

    def _fetch_generate_and_save():
        # Get team object
        team = Team.objects.get(id=team_id)

        # Parse timestamp to create date range
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

        # Get the trace data
        llm_trace = response.results[0]

        # Convert to format for text repr
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

        # Generate text representation
        options: FormatterOptions = {
            "include_line_numbers": True,
            "truncated": False,
            "include_markers": False,
            "collapsed": False,
        }

        text_repr = format_trace_text_repr(
            trace=trace_dict,
            hierarchy=hierarchy,
            options=options,
        )

        # Generate summary using LLM (this is async and will be awaited outside)
        return trace_dict, hierarchy, text_repr, team

    # Fetch trace data and prepare (sync operation)
    trace, hierarchy, text_repr, team = await database_sync_to_async(_fetch_generate_and_save, thread_sensitive=False)()

    # Generate summary using LLM
    summary_result = await summarize(
        text_repr=text_repr,
        team_id=team_id,
        trace_id=trace_id,
        mode=mode,
        model=model,
    )

    # Save event to ClickHouse immediately
    def _save_event():
        from posthog.models.event.util import create_event

        event_uuid = uuid4()
        timestamp = datetime.now()

        # Serialize summary bullets and notes as JSON strings
        import json

        summary_bullets_json = json.dumps([bullet.model_dump() for bullet in summary_result.summary_bullets])
        summary_notes_json = json.dumps([note.model_dump() for note in summary_result.interesting_notes])

        # Create event properties with flattened summary fields
        properties = {
            constants.PROP_TRACE_ID: trace_id,
            constants.PROP_BATCH_RUN_ID: batch_run_id,
            constants.PROP_SUMMARY_MODE: mode,
            constants.PROP_SUMMARY_TITLE: summary_result.title,
            constants.PROP_SUMMARY_TEXT_REPR: text_repr,
            constants.PROP_SUMMARY_FLOW_DIAGRAM: summary_result.flow_diagram,
            constants.PROP_SUMMARY_BULLETS: summary_bullets_json,
            constants.PROP_SUMMARY_INTERESTING_NOTES: summary_notes_json,
            constants.PROP_TEXT_REPR_LENGTH: len(text_repr),
            constants.PROP_EVENT_COUNT: len(hierarchy),
        }

        # Use low-level ClickHouse insert
        create_event(
            event_uuid=event_uuid,
            event=constants.EVENT_NAME_TRACE_SUMMARY,
            team=team,
            distinct_id=f"trace_summary_{team_id}",
            timestamp=timestamp,
            properties=properties,
            person_id=None,
        )

    await database_sync_to_async(_save_event, thread_sensitive=False)()

    return {
        "trace_id": trace_id,
        "success": True,
        "text_repr_length": len(text_repr),
        "event_count": len(hierarchy),
    }
