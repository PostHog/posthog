"""Activity for fetching trace/generation data and storing formatted text in Redis."""

import time

import structlog
import temporalio

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team
from posthog.redis import get_async_client
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.llm_analytics.trace_summarization.constants import MAX_RAW_TRACE_SIZE
from posthog.temporal.llm_analytics.trace_summarization.models import (
    FetchAndFormatInput,
    FetchAndFormatResult,
    FetchResult,
)
from posthog.temporal.llm_analytics.trace_summarization.queries import fetch_trace
from posthog.temporal.llm_analytics.trace_summarization.state import generate_redis_key, store_text_repr
from posthog.temporal.llm_analytics.trace_summarization.utils import format_datetime_for_clickhouse

from products.llm_analytics.backend.text_repr.formatters import (
    FormatterOptions,
    format_trace_text_repr,
    llm_trace_to_formatter_format,
)

logger = structlog.get_logger(__name__)


def _fetch_and_format_trace(
    trace_id: str, team_id: int, window_start: str, window_end: str, max_length: int | None = None
) -> FetchResult | None:
    """Fetch trace data and format text representation.

    Returns FetchResult with text_repr=None if oversized, or None if not found.
    """
    team = Team.objects.get(id=team_id)

    llm_trace = fetch_trace(team, trace_id, window_start, window_end)
    if llm_trace is None:
        return None

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
        _trace_dict, hierarchy = llm_trace_to_formatter_format(llm_trace)
        return FetchResult(text_repr=None, event_count=len(hierarchy))

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

    return FetchResult(text_repr=text_repr, event_count=len(hierarchy))


def _fetch_and_format_generation(
    generation_id: str, team_id: int, window_start: str, window_end: str, max_length: int | None = None
) -> FetchResult | None:
    """Fetch generation event data and format text representation.

    Returns FetchResult or None if not found.
    """
    team = Team.objects.get(id=team_id)

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

    text_repr = _format_generation_text_repr(generation_dict)

    if max_length and len(text_repr) > max_length:
        text_repr = text_repr[:max_length] + "\n... [truncated]"

    return FetchResult(text_repr=text_repr, event_count=1)


def _format_generation_text_repr(generation_data: dict) -> str:
    """Format a generation event into a text representation for LLM summarization."""
    parts = []

    parts.append("=== LLM Generation Event ===")
    parts.append("")

    if generation_data.get("model"):
        parts.append(f"Model: {generation_data['model']}")
    if generation_data.get("provider"):
        parts.append(f"Provider: {generation_data['provider']}")

    input_tokens = generation_data.get("input_tokens")
    output_tokens = generation_data.get("output_tokens")
    if input_tokens is not None or output_tokens is not None:
        tokens_str = []
        if input_tokens is not None:
            tokens_str.append(f"input={input_tokens}")
        if output_tokens is not None:
            tokens_str.append(f"output={output_tokens}")
        parts.append(f"Tokens: {', '.join(tokens_str)}")

    latency = generation_data.get("latency")
    if latency is not None:
        parts.append(f"Latency: {latency:.2f}s")

    parts.append("")

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
async def fetch_and_format_activity(input: FetchAndFormatInput) -> FetchAndFormatResult:
    """Fetch trace or generation data, format text representation, and store in Redis."""
    item_type = "generation" if input.generation_id else "trace"
    item_id = input.generation_id or input.trace_id
    log = logger.bind(trace_id=input.trace_id, generation_id=input.generation_id, team_id=input.team_id)

    async with Heartbeater():
        t0 = time.monotonic()

        if input.generation_id:
            result = await database_sync_to_async(_fetch_and_format_generation, thread_sensitive=False)(
                input.generation_id, input.team_id, input.window_start, input.window_end, input.max_length
            )
        else:
            result = await database_sync_to_async(_fetch_and_format_trace, thread_sensitive=False)(
                input.trace_id, input.team_id, input.window_start, input.window_end, input.max_length
            )

        fetch_duration_s = time.monotonic() - t0

        # Not found
        if result is None:
            skip_reason = "generation_not_found" if input.generation_id else "trace_not_found"
            log.warning(
                f"Skipping {item_type} - not found in time window",
                fetch_duration_s=round(fetch_duration_s, 2),
            )
            return FetchAndFormatResult(
                redis_key="",
                trace_id=input.trace_id,
                team_id=input.team_id,
                trace_first_timestamp=input.trace_first_timestamp,
                generation_id=input.generation_id,
                skipped=True,
                skip_reason=skip_reason,
            )

        # Oversized trace (text_repr is None but event_count is known)
        if result.text_repr is None:
            log.warning(
                "Skipping trace - exceeds max raw size",
                fetch_duration_s=round(fetch_duration_s, 2),
                event_count=result.event_count,
            )
            return FetchAndFormatResult(
                redis_key="",
                trace_id=input.trace_id,
                team_id=input.team_id,
                trace_first_timestamp=input.trace_first_timestamp,
                generation_id=input.generation_id,
                event_count=result.event_count,
                skipped=True,
                skip_reason="trace_too_large",
            )

        # Store in Redis
        redis_key = generate_redis_key(item_type, input.team_id, item_id)
        redis_client = get_async_client()
        compressed_size = await store_text_repr(redis_client, redis_key, result.text_repr)

        log.info(
            f"{item_type.capitalize()} fetched and formatted",
            fetch_duration_s=round(fetch_duration_s, 2),
            text_repr_length=len(result.text_repr),
            compressed_size=compressed_size,
            event_count=result.event_count,
        )

        return FetchAndFormatResult(
            redis_key=redis_key,
            trace_id=input.trace_id,
            team_id=input.team_id,
            trace_first_timestamp=input.trace_first_timestamp,
            text_repr_length=len(result.text_repr),
            compressed_size=compressed_size,
            event_count=result.event_count,
            generation_id=input.generation_id,
        )
