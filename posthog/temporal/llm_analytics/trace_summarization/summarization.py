"""Activity for generating trace summaries using LLM."""

from uuid import uuid4

import structlog
import temporalio

from posthog.schema import DateRange, TraceQuery

from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner
from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.llm_analytics.trace_summarization import constants
from posthog.temporal.llm_analytics.trace_summarization.models import SummarizationActivityResult

from products.llm_analytics.backend.summarization.llm import summarize
from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse
from products.llm_analytics.backend.summarization.models import (
    GeminiModel,
    OpenAIModel,
    SummarizationMode,
    SummarizationProvider,
)
from products.llm_analytics.backend.text_repr.formatters import (
    FormatterOptions,
    format_trace_text_repr,
    llm_trace_to_formatter_format,
)

from ee.hogai.llm_traces_summaries.constants import LLM_TRACES_SUMMARIES_DOCUMENT_TYPE, LLM_TRACES_SUMMARIES_PRODUCT
from ee.hogai.llm_traces_summaries.tools.embed_summaries import LLMTracesSummarizerEmbedder

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def generate_and_save_summary_activity(
    trace_id: str,
    team_id: int,
    window_start: str,
    window_end: str,
    mode: str,
    batch_run_id: str,
    provider: str,
    model: str | None = None,
    max_length: int | None = None,
) -> SummarizationActivityResult:
    """
    Generate summary for a trace and save it to ClickHouse.

    Fetches trace data, generates LLM summary, and saves it as an event.
    Saves directly to avoid passing large objects through workflow history.
    """

    def _fetch_trace_and_format(
        trace_id: str, team_id: int, window_start: str, window_end: str, max_length: int | None = None
    ) -> tuple[dict, list, str, Team, str] | None:
        """Fetch trace data and format text representation.

        Returns tuple of (trace_dict, hierarchy, text_repr, team, trace_timestamp) or None if not found.
        trace_timestamp is the first event timestamp of the trace (ISO format).
        """
        team = Team.objects.get(id=team_id)

        query = TraceQuery(
            traceId=trace_id,
            dateRange=DateRange(date_from=window_start, date_to=window_end),
        )

        runner = TraceQueryRunner(team=team, query=query)
        response = runner.calculate()

        if not response.results:
            return None  # Trace not found in window

        llm_trace = response.results[0]
        trace_dict, hierarchy = llm_trace_to_formatter_format(llm_trace)
        # Extract the trace's first event timestamp for efficient linking
        trace_timestamp = llm_trace.createdAt

        options: FormatterOptions = {
            "include_line_numbers": True,
            "truncated": False,
            "include_markers": False,
            "collapsed": False,
            "max_length": max_length,
        }

        text_repr, _ = format_trace_text_repr(
            trace=trace_dict,
            hierarchy=hierarchy,
            options=options,
        )

        return trace_dict, hierarchy, text_repr, team, trace_timestamp

    def _save_summary_event(
        summary_result: SummarizationResponse, hierarchy: list, text_repr: str, team: Team, trace_timestamp: str
    ) -> None:
        """Save summary as $ai_trace_summary event to ClickHouse."""

        event_uuid = uuid4()

        summary_bullets_json = [bullet.model_dump() for bullet in summary_result.summary_bullets]
        summary_notes_json = [note.model_dump() for note in summary_result.interesting_notes]

        properties = {
            "$ai_trace_id": trace_id,
            "$ai_batch_run_id": batch_run_id,
            "$ai_summary_mode": mode,
            "$ai_summary_title": summary_result.title,
            "$ai_summary_flow_diagram": summary_result.flow_diagram,
            "$ai_summary_bullets": summary_bullets_json,
            "$ai_summary_interesting_notes": summary_notes_json,
            "$ai_text_repr_length": len(text_repr),
            "$ai_event_count": len(hierarchy),
            "trace_timestamp": trace_timestamp,
        }

        create_event(
            event_uuid=event_uuid,
            event=constants.EVENT_NAME_TRACE_SUMMARY,
            team=team,
            distinct_id=f"trace_summary_{team_id}",
            properties=properties,
        )

    def _embed_summary(summary_result: SummarizationResponse, team: Team) -> None:
        """Generate embedding for the summary and send to Kafka."""
        # Format summary text for embedding
        parts = []
        if summary_result.title:
            parts.append(f"Title: {summary_result.title}")
        if summary_result.flow_diagram:
            parts.append(f"\nFlow:\n{summary_result.flow_diagram}")
        if summary_result.summary_bullets:
            bullets_text = "\n".join(f"- {b.text}" for b in summary_result.summary_bullets)
            parts.append(f"\nSummary:\n{bullets_text}")
        if summary_result.interesting_notes:
            notes_text = "\n".join(f"- {n.text}" for n in summary_result.interesting_notes)
            parts.append(f"\nInteresting Notes:\n{notes_text}")

        summary_text = "\n".join(parts)
        # Use batch_run_id as rendering to link embeddings to their source summarization run
        # Use mode suffix in document_type to distinguish detailed vs minimal summaries
        document_type_with_mode = f"{LLM_TRACES_SUMMARIES_DOCUMENT_TYPE}-{mode}"

        embedder = LLMTracesSummarizerEmbedder(team=team)
        embedder._embed_document(
            content=summary_text,
            document_id=trace_id,
            document_type=document_type_with_mode,
            rendering=batch_run_id,
            product=LLM_TRACES_SUMMARIES_PRODUCT,
        )

    # Fetch trace data and format text representation
    result = await database_sync_to_async(_fetch_trace_and_format, thread_sensitive=False)(
        trace_id, team_id, window_start, window_end, max_length
    )

    # Handle trace not found in window
    if result is None:
        logger.warning(
            "Skipping trace - not found in time window",
            trace_id=trace_id,
            window_start=window_start,
            window_end=window_end,
        )
        return SummarizationActivityResult(
            trace_id=trace_id,
            success=False,
            skipped=True,
            skip_reason="trace_not_found",
        )

    _trace, hierarchy, text_repr, team, trace_timestamp = result

    # Generate summary using LLM
    # Note: text_repr is automatically reduced to fit LLM context if needed (see format_trace_text_repr)
    # Convert string inputs to enum types
    mode_enum = SummarizationMode(mode)
    provider_enum = SummarizationProvider(provider)
    model_enum: OpenAIModel | GeminiModel | None = None
    if model:
        if provider_enum == SummarizationProvider.GEMINI:
            model_enum = GeminiModel(model)
        else:
            model_enum = OpenAIModel(model)

    summary_result = await summarize(
        text_repr=text_repr,
        team_id=team_id,
        mode=mode_enum,
        provider=provider_enum,
        model=model_enum,
    )

    # Save event to ClickHouse immediately
    await database_sync_to_async(_save_summary_event, thread_sensitive=False)(
        summary_result, hierarchy, text_repr, team, trace_timestamp
    )

    # Request embedding by sending to Kafka
    embedding_requested = False
    embedding_request_error = None
    try:
        await database_sync_to_async(_embed_summary, thread_sensitive=False)(summary_result, team)
        embedding_requested = True
    except Exception as e:
        embedding_request_error = str(e)
        logger.exception(
            "Failed to request embedding for trace summary",
            trace_id=trace_id,
            error=embedding_request_error,
        )

    return SummarizationActivityResult(
        trace_id=trace_id,
        success=True,
        text_repr_length=len(text_repr),
        event_count=len(hierarchy),
        embedding_requested=embedding_requested,
        embedding_request_error=embedding_request_error,
    )
