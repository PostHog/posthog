"""Activity for generating trace summaries using LLM."""

import time
from uuid import uuid4

import structlog
import temporalio

from posthog.schema import DateRange, TraceQuery

from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner
from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.llm_analytics.trace_summarization import constants
from posthog.temporal.llm_analytics.trace_summarization.constants import MAX_RAW_TRACE_SIZE
from posthog.temporal.llm_analytics.trace_summarization.models import SummarizationActivityResult

from products.llm_analytics.backend.summarization.llm import summarize
from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse
from products.llm_analytics.backend.summarization.models import OpenAIModel, SummarizationMode
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
    trace_first_timestamp: str,
    team_id: int,
    window_start: str,
    window_end: str,
    mode: str,
    batch_run_id: str,
    model: str | None = None,
    max_length: int | None = None,
) -> SummarizationActivityResult:
    """
    Generate summary for a trace and save it to ClickHouse.

    Fetches trace data, generates LLM summary, and saves it as an event.
    Saves directly to avoid passing large objects through workflow history.

    Args:
        trace_first_timestamp: The first event timestamp of the trace,
            provided by sampling for navigation in the cluster scatter plot.
    """

    def _fetch_trace_and_format(
        trace_id: str, team_id: int, window_start: str, window_end: str, max_length: int | None = None
    ) -> tuple[dict, list, str, Team] | tuple[dict, list, None, Team] | None:
        """Fetch trace data and format text representation.

        Returns tuple of (trace_dict, hierarchy, text_repr, team) or None if not found.
        text_repr is None if the trace exceeds MAX_RAW_TRACE_SIZE.
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

        # Estimate raw size before expensive formatting
        raw_size = sum(len(str(e.properties)) for e in llm_trace.events)
        if raw_size > MAX_RAW_TRACE_SIZE:
            logger.warning(
                "Skipping oversized trace",
                trace_id=trace_id,
                team_id=team_id,
                event_count=len(llm_trace.events),
                raw_size=raw_size,
                max_raw_size=MAX_RAW_TRACE_SIZE,
            )
            trace_dict, hierarchy = llm_trace_to_formatter_format(llm_trace)
            return trace_dict, hierarchy, None, team

        trace_dict, hierarchy = llm_trace_to_formatter_format(llm_trace)

        options: FormatterOptions = {
            "include_line_numbers": True,
            "truncated": True,
            "include_markers": False,
            "collapsed": False,
            "max_length": max_length,
        }

        text_repr, _ = format_trace_text_repr(
            trace=trace_dict,
            hierarchy=hierarchy,
            options=options,
        )

        return trace_dict, hierarchy, text_repr, team

    def _save_summary_event(summary_result: SummarizationResponse, hierarchy: list, text_repr: str, team: Team) -> None:
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
            "trace_timestamp": trace_first_timestamp,
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

    activity_start = time.monotonic()
    log = logger.bind(trace_id=trace_id, team_id=team_id)

    async with Heartbeater():
        # Step 1: Fetch trace data and format text representation
        t0 = time.monotonic()
        result = await database_sync_to_async(_fetch_trace_and_format, thread_sensitive=False)(
            trace_id, team_id, window_start, window_end, max_length
        )
        fetch_duration_s = time.monotonic() - t0

        # Handle trace not found in window
        if result is None:
            log.warning(
                "Skipping trace - not found in time window",
                fetch_duration_s=round(fetch_duration_s, 2),
                window_start=window_start,
                window_end=window_end,
            )
            return SummarizationActivityResult(
                trace_id=trace_id,
                success=False,
                skipped=True,
                skip_reason="trace_not_found",
            )

        _trace, hierarchy, text_repr, team = result

        # Handle oversized trace (raw data exceeded MAX_RAW_TRACE_SIZE)
        if text_repr is None:
            log.warning(
                "Skipping trace - exceeds max raw size",
                fetch_duration_s=round(fetch_duration_s, 2),
                event_count=len(hierarchy),
            )
            return SummarizationActivityResult(
                trace_id=trace_id,
                success=False,
                skipped=True,
                skip_reason="trace_too_large",
            )

        log.info(
            "Trace fetched and formatted",
            fetch_duration_s=round(fetch_duration_s, 2),
            text_repr_length=len(text_repr),
            event_count=len(hierarchy),
        )

        # Step 2: Generate summary using LLM via gateway
        mode_enum = SummarizationMode(mode)
        model_enum = OpenAIModel(model) if model else None

        t0 = time.monotonic()
        summary_result = await database_sync_to_async(summarize, thread_sensitive=False)(
            text_repr=text_repr,
            team_id=team_id,
            mode=mode_enum,
            model=model_enum,
            user_id=f"temporal-workflow-team-{team_id}",
        )
        llm_duration_s = time.monotonic() - t0
        log.info(
            "LLM summary generated",
            llm_duration_s=round(llm_duration_s, 2),
            text_repr_length=len(text_repr),
            model=model,
        )

        # Step 3: Save event to ClickHouse
        t0 = time.monotonic()
        await database_sync_to_async(_save_summary_event, thread_sensitive=False)(
            summary_result, hierarchy, text_repr, team
        )
        save_duration_s = time.monotonic() - t0

        # Step 4: Request embedding by sending to Kafka
        embedding_requested = False
        embedding_request_error = None
        t0 = time.monotonic()
        try:
            await database_sync_to_async(_embed_summary, thread_sensitive=False)(summary_result, team)
            embedding_requested = True
        except Exception as e:
            embedding_request_error = str(e)
            log.exception(
                "Failed to request embedding for trace summary",
                error=embedding_request_error,
            )
        embed_duration_s = time.monotonic() - t0

        total_duration_s = time.monotonic() - activity_start
        log.info(
            "Activity completed",
            total_duration_s=round(total_duration_s, 2),
            fetch_duration_s=round(fetch_duration_s, 2),
            llm_duration_s=round(llm_duration_s, 2),
            save_duration_s=round(save_duration_s, 2),
            embed_duration_s=round(embed_duration_s, 2),
            text_repr_length=len(text_repr),
            event_count=len(hierarchy),
            embedding_requested=embedding_requested,
        )

    return SummarizationActivityResult(
        trace_id=trace_id,
        success=True,
        text_repr_length=len(text_repr),
        event_count=len(hierarchy),
        embedding_requested=embedding_requested,
        embedding_request_error=embedding_request_error,
    )
