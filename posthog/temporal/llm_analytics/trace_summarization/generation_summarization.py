"""Activity for generating summaries of individual $ai_generation events using LLM."""

from uuid import uuid4

import structlog
import temporalio

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.llm_analytics.trace_summarization import constants
from posthog.temporal.llm_analytics.trace_summarization.models import SummarizationActivityResult
from posthog.temporal.llm_analytics.trace_summarization.utils import format_datetime_for_clickhouse

from products.llm_analytics.backend.summarization.llm import summarize
from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse
from products.llm_analytics.backend.summarization.models import (
    GeminiModel,
    OpenAIModel,
    SummarizationMode,
    SummarizationProvider,
)

from ee.hogai.llm_traces_summaries.tools.embed_summaries import LLMTracesSummarizerEmbedder

logger = structlog.get_logger(__name__)


def _format_generation_text_repr(generation_data: dict) -> str:
    """Format a generation event into a text representation for LLM summarization."""
    parts = []

    # Header
    parts.append("=== LLM Generation Event ===")
    parts.append("")

    # Model and provider info
    if generation_data.get("model"):
        parts.append(f"Model: {generation_data['model']}")
    if generation_data.get("provider"):
        parts.append(f"Provider: {generation_data['provider']}")

    # Token usage
    input_tokens = generation_data.get("input_tokens")
    output_tokens = generation_data.get("output_tokens")
    if input_tokens is not None or output_tokens is not None:
        tokens_str = []
        if input_tokens is not None:
            tokens_str.append(f"input={input_tokens}")
        if output_tokens is not None:
            tokens_str.append(f"output={output_tokens}")
        parts.append(f"Tokens: {', '.join(tokens_str)}")

    # Latency
    latency = generation_data.get("latency")
    if latency is not None:
        parts.append(f"Latency: {latency:.2f}s")

    parts.append("")

    # Input/prompt
    input_content = generation_data.get("input")
    if input_content:
        parts.append("--- Input ---")
        if isinstance(input_content, list):
            for msg in input_content:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                parts.append(f"[{role}]: {content}")
        else:
            parts.append(str(input_content))
        parts.append("")

    # Output/response
    output_content = generation_data.get("output")
    if output_content:
        parts.append("--- Output ---")
        if isinstance(output_content, list):
            for msg in output_content:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                parts.append(f"[{role}]: {content}")
        else:
            parts.append(str(output_content))

    return "\n".join(parts)


@temporalio.activity.defn
async def generate_and_save_generation_summary_activity(
    generation_id: str,
    trace_id: str,
    trace_first_timestamp: str,
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
    Generate summary for a single $ai_generation event and save it to ClickHouse.

    Fetches generation data, generates LLM summary, and saves it as an event.
    Saves directly to avoid passing large objects through workflow history.

    Args:
        trace_first_timestamp: The first event timestamp of the parent trace,
            used for navigation in the cluster scatter plot.
    """

    def _fetch_generation_data(
        generation_id: str, team_id: int, window_start: str, window_end: str
    ) -> tuple[dict, Team] | None:
        """Fetch generation event data.

        Returns tuple of (generation_dict, team) or None if not found.
        """
        team = Team.objects.get(id=team_id)

        # Convert ISO format to ClickHouse-compatible format
        start_dt_str = format_datetime_for_clickhouse(window_start)
        end_dt_str = format_datetime_for_clickhouse(window_end)

        query = parse_select(
            """
            SELECT
                properties.$ai_model as model,
                properties.$ai_provider as provider,
                properties.$ai_input as input,
                properties.$ai_output as output,
                properties.$ai_input_tokens as input_tokens,
                properties.$ai_output_tokens as output_tokens,
                properties.$ai_latency as latency
            FROM events
            WHERE event = '$ai_generation'
                AND timestamp >= toDateTime({start_dt}, 'UTC')
                AND timestamp < toDateTime({end_dt}, 'UTC')
                AND uuid = {generation_id}
            LIMIT 1
            """
        )

        result = execute_hogql_query(
            query_type="GenerationForSummarization",
            query=query,
            placeholders={
                "start_dt": ast.Constant(value=start_dt_str),
                "end_dt": ast.Constant(value=end_dt_str),
                "generation_id": ast.Constant(value=generation_id),
            },
            team=team,
        )

        if not result.results:
            return None

        row = result.results[0]
        generation_dict = {
            "model": row[0],
            "provider": row[1],
            "input": row[2],
            "output": row[3],
            "input_tokens": row[4],
            "output_tokens": row[5],
            "latency": row[6],
        }

        return generation_dict, team

    def _save_summary_event(
        summary_result: SummarizationResponse,
        text_repr: str,
        team: Team,
    ) -> None:
        """Save summary as $ai_generation_summary event to ClickHouse."""

        event_uuid = uuid4()

        summary_bullets_json = [bullet.model_dump() for bullet in summary_result.summary_bullets]
        summary_notes_json = [note.model_dump() for note in summary_result.interesting_notes]

        properties = {
            "$ai_generation_id": generation_id,
            "$ai_trace_id": trace_id,
            "$ai_batch_run_id": batch_run_id,
            "$ai_summary_mode": mode,
            "$ai_summary_title": summary_result.title,
            "$ai_summary_flow_diagram": summary_result.flow_diagram,
            "$ai_summary_bullets": summary_bullets_json,
            "$ai_summary_interesting_notes": summary_notes_json,
            "$ai_text_repr_length": len(text_repr),
            "trace_timestamp": trace_first_timestamp,
        }

        create_event(
            event_uuid=event_uuid,
            event=constants.EVENT_NAME_GENERATION_SUMMARY,
            team=team,
            distinct_id=f"generation_summary_{team_id}",
            properties=properties,
        )

    def _embed_summary(summary_result: SummarizationResponse, team: Team) -> None:
        """Generate embedding for the summary and send to Kafka."""
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

        embedder = LLMTracesSummarizerEmbedder(team=team)
        embedder._embed_document(
            content=summary_text,
            document_id=generation_id,
            document_type=constants.GENERATION_DOCUMENT_TYPE,
            rendering=batch_run_id,
            product="llm-analytics",
        )

    # Fetch generation data
    result = await database_sync_to_async(_fetch_generation_data, thread_sensitive=False)(
        generation_id, team_id, window_start, window_end
    )

    if result is None:
        logger.warning(
            "Skipping generation - not found in time window",
            generation_id=generation_id,
            window_start=window_start,
            window_end=window_end,
        )
        return SummarizationActivityResult(
            trace_id=trace_id,
            success=False,
            generation_id=generation_id,
            skipped=True,
            skip_reason="generation_not_found",
        )

    generation_dict, team = result

    # Format text representation
    text_repr = _format_generation_text_repr(generation_dict)

    # Apply max_length truncation if needed
    if max_length and len(text_repr) > max_length:
        text_repr = text_repr[:max_length] + "\n... [truncated]"

    # Generate summary using LLM
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

    # Save event to ClickHouse
    await database_sync_to_async(_save_summary_event, thread_sensitive=False)(summary_result, text_repr, team)

    # Request embedding
    embedding_requested = False
    embedding_request_error = None
    try:
        await database_sync_to_async(_embed_summary, thread_sensitive=False)(summary_result, team)
        embedding_requested = True
    except Exception as e:
        embedding_request_error = str(e)
        logger.exception(
            "Failed to request embedding for generation summary",
            generation_id=generation_id,
            error=embedding_request_error,
        )

    return SummarizationActivityResult(
        trace_id=trace_id,
        success=True,
        generation_id=generation_id,
        text_repr_length=len(text_repr),
        event_count=1,  # Single generation event
        embedding_requested=embedding_requested,
        embedding_request_error=embedding_request_error,
    )
