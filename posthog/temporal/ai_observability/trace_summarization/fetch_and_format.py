"""Activity for fetching trace/generation data and storing formatted text in Redis."""

import time

import structlog
import temporalio

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.models.team import Team
from posthog.redis import get_async_client
from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.trace_summarization.constants import MAX_RAW_TRACE_SIZE
from posthog.temporal.ai_observability.trace_summarization.models import (
    FetchAndFormatInput,
    FetchAndFormatResult,
    FetchResult,
)
from posthog.temporal.ai_observability.trace_summarization.queries import fetch_trace
from posthog.temporal.ai_observability.trace_summarization.state import generate_redis_key, store_text_repr
from posthog.temporal.ai_observability.trace_summarization.utils import format_datetime_for_clickhouse
from posthog.temporal.common.heartbeat import Heartbeater

from products.ai_observability.backend.text_repr.formatters import (
    FormatterOptions,
    format_trace_text_repr,
    llm_trace_to_formatter_format,
)

logger = structlog.get_logger(__name__)


def _fetch_and_format_trace(
    trace_id: str,
    team_id: int,
    window_start: str,
    window_end: str,
    max_length: int | None = None,
    *,
    max_trace_events: int | None = None,
    max_raw_trace_size: int | None = None,
) -> FetchResult | None:
    """Fetch trace data and format text representation.

    Returns FetchResult with text_repr=None if oversized, or None if not found.
    """
    team = Team.objects.get(id=team_id)

    llm_trace = fetch_trace(team, trace_id, window_start, window_end)
    if llm_trace is None:
        return None

    event_count = len(llm_trace.events)
    if max_trace_events is not None and event_count > max_trace_events:
        logger.warning(
            "Skipping trace with too many events",
            trace_id=trace_id,
            team_id=team_id,
            event_count=event_count,
            max_trace_events=max_trace_events,
        )
        return FetchResult(text_repr=None, event_count=event_count)

    raw_size = sum(len(str(e.properties)) for e in llm_trace.events)
    raw_size_limit = max_raw_trace_size if max_raw_trace_size is not None else MAX_RAW_TRACE_SIZE
    if raw_size > raw_size_limit:
        logger.warning(
            "Skipping oversized trace",
            trace_id=trace_id,
            team_id=team_id,
            event_count=event_count,
            raw_size=raw_size,
            max_raw_size=raw_size_limit,
        )
        return FetchResult(text_repr=None, event_count=event_count)

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
    generation_id: str,
    trace_id: str,
    team_id: int,
    window_start: str,
    window_end: str,
    max_length: int | None = None,
) -> FetchResult | None:
    """Fetch generation event data and format text representation.

    Returns FetchResult or None if not found.

    `trace_id` is required and used as a WHERE filter — it's the first variable
    segment of the `ai_events` sorting key (`team_id, trace_id, timestamp`) and
    of the sharding key, so adding it prunes the query to a single shard plus a
    range scan instead of a fan-out across all shards. The caller
    (`fetch_and_format_activity`) always has it set on `FetchAndFormatInput`.
    """
    team = Team.objects.get(id=team_id)

    start_dt_str = format_datetime_for_clickhouse(window_start)
    end_dt_str = format_datetime_for_clickhouse(window_end)

    # Query the dedicated table first; the resolver rewrites + re-runs against the
    # shared `events` table when ai_events returns zero rows (data beyond the
    # retention window). Heavy columns (`input`, `output`, `output_choices`) live
    # only as native columns on ai_events, so only this path can recover them for
    # recent rows.
    # Chat-format SDK calls (most OpenAI/Anthropic) record the result in `$ai_output_choices`
    # and leave `$ai_output` empty. Read choices first, the same precedence the canonical
    # formatter uses (`format_output_messages`).
    query = parse_select(
        """
        SELECT
            model,
            provider,
            input,
            coalesce(
                nullIf(output_choices, ''),
                output
            ) as output,
            input_tokens,
            output_tokens,
            latency
        FROM posthog.ai_events AS ai_events
        WHERE event = '$ai_generation'
            AND trace_id = {trace_id}
            AND timestamp >= toDateTime({start_dt}, 'UTC')
            AND timestamp < toDateTime({end_dt}, 'UTC')
            AND uuid = {generation_id}
        LIMIT 1
        """
    )

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        result = query_ai_events(
            query=query,
            placeholders={
                "start_dt": ast.Constant(value=start_dt_str),
                "end_dt": ast.Constant(value=end_dt_str),
                "generation_id": ast.Constant(value=generation_id),
                "trace_id": ast.Constant(value=trace_id),
            },
            team=team,
            query_type="GenerationForSummarization",
            fall_back_to_events=True,
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

    text_repr = _format_generation_text_repr(generation_dict, max_length=max_length)

    return FetchResult(text_repr=text_repr, event_count=1)


GENERATION_SECTION_TRUNCATION_MARKER = "\n... [truncated] ...\n"


def _render_generation_messages(content: object) -> str:
    """Render a generation's input or output messages into a text block.

    Returns an empty string when there is no content, so the caller drops the whole section.
    """
    if not content:
        return ""
    if isinstance(content, list):
        return "\n".join(f"[{msg.get('role', 'unknown')}]: {msg.get('content', '')}" for msg in content)
    return str(content)


def _truncate_section(text: str, budget: int) -> str:
    """Truncate one section's text to at most `budget` characters, marking the cut.

    Keeps the head and the tail with the marker between them, because both ends matter:
    the head carries the system prompt and the tail carries the newest messages.
    """
    if budget <= 0:
        return ""
    if len(text) <= budget:
        return text
    keep = budget - len(GENERATION_SECTION_TRUNCATION_MARKER)
    if keep <= 0:
        return text[:budget]
    tail = keep // 2
    head = keep - tail
    return text[:head] + GENERATION_SECTION_TRUNCATION_MARKER + text[len(text) - tail :]


@frozen
class _BudgetedSections:
    """A generation's input and output blocks after sharing the character budget."""

    input_block: str
    output_block: str


def _split_section_budget(input_block: str, output_block: str, budget: int) -> _BudgetedSections:
    """Split `budget` characters between the input and output blocks.

    A block that already fits gives its slack to the other, so the full budget is used. When both
    are oversized, each keeps half. The output block is never dropped to fit a large input, because
    a summary that describes only the prompt and omits the model result is close to useless for
    clustering and search.
    """
    if len(input_block) + len(output_block) <= budget:
        return _BudgetedSections(input_block=input_block, output_block=output_block)
    half = budget // 2
    if len(input_block) <= half:
        return _BudgetedSections(
            input_block=input_block, output_block=_truncate_section(output_block, budget - len(input_block))
        )
    if len(output_block) <= half:
        return _BudgetedSections(
            input_block=_truncate_section(input_block, budget - len(output_block)), output_block=output_block
        )
    return _BudgetedSections(
        input_block=_truncate_section(input_block, half), output_block=_truncate_section(output_block, budget - half)
    )


def _format_generation_text_repr(generation_data: dict, max_length: int | None = None) -> str:
    """Format a generation event into a text representation for LLM summarization.

    When `max_length` is set, the input and output sections share the budget so a large input
    cannot push the output section out entirely. Both sections stay represented, each truncated to
    its share.
    """
    header_parts = ["=== LLM Generation Event ===", ""]

    if generation_data.get("model"):
        header_parts.append(f"Model: {generation_data['model']}")
    if generation_data.get("provider"):
        header_parts.append(f"Provider: {generation_data['provider']}")

    input_tokens = generation_data.get("input_tokens")
    output_tokens = generation_data.get("output_tokens")
    if input_tokens is not None or output_tokens is not None:
        tokens_str = []
        if input_tokens is not None:
            tokens_str.append(f"input={input_tokens}")
        if output_tokens is not None:
            tokens_str.append(f"output={output_tokens}")
        header_parts.append(f"Tokens: {', '.join(tokens_str)}")

    latency = generation_data.get("latency")
    if latency is not None:
        header_parts.append(f"Latency: {latency:.2f}s")

    header_parts.append("")

    input_block = _render_generation_messages(generation_data.get("input"))
    output_block = _render_generation_messages(generation_data.get("output"))

    def assemble(in_block: str, out_block: str) -> str:
        parts = list(header_parts)
        if in_block:
            parts.extend(("--- Input ---", in_block, ""))
        if out_block:
            parts.extend(("--- Output ---", out_block))
        return "\n".join(parts)

    text_repr = assemble(input_block, output_block)
    if max_length is None or len(text_repr) <= max_length:
        return text_repr

    # `overhead` is the header, section markers, and blank lines, so the split budgets only the
    # two content blocks and the reassembled text stays within `max_length`.
    overhead = len(text_repr) - len(input_block) - len(output_block)
    sections = _split_section_budget(input_block, output_block, max(max_length - overhead, 0))
    return assemble(sections.input_block, sections.output_block)


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
                input.generation_id,
                input.trace_id,
                input.team_id,
                input.window_start,
                input.window_end,
                input.max_length,
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
