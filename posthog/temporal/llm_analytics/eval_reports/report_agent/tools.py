"""Tool definitions for the evaluation report agent.

Uses LangGraph's InjectedState pattern so tools can access graph state directly.
All query tools hit ClickHouse live via HogQL since the dataset is too large/variable
to pre-load. Output tools mutate `state["report"]` (an EvalReportContent instance)
via list append / attribute set — in-place mutations propagate back through
InjectedState, but whole-key replacement does not.
"""

import re
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from posthog.hogql import ast

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import MAX_REPORT_SECTIONS, Citation, ReportSection

if TYPE_CHECKING:
    from posthog.models import Team

# Strict UUID match for validating IDs before string-interpolating into HogQL
# and before storing in Citation. Generation IDs reach this code from the LLM,
# which can relay arbitrary `$ai_target_event_id` property values set by user
# instrumentation. Trace IDs have the same trust boundary.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _ch_ts(iso_str: str) -> datetime:
    """Parse an ISO-8601 timestamp and return a UTC-aware datetime.

    Returns a datetime (not a string) so HogQL's printer serializes it as
    `toDateTime64(..., 6, <team_tz>)` with correct timezone alignment against
    the events.timestamp column (DateTime64(6, <team_tz>)). Passing a bare
    string here caused ClickHouse to coerce via the team's timezone, silently
    shifting UTC moments by the team's offset so every period query returned
    zero matches.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


_WIDENED_TS_START_SENTINEL = "2020-01-01T00:00:00+00:00"
_WIDENED_TS_END_SENTINEL = "2099-01-01T00:00:00+00:00"


def _widened_ts_window(state: dict) -> tuple[datetime, datetime]:
    """Return (ts_start, ts_end) datetimes widened for generation-event lookups.

    Generations predate their evals, so widen the start by 7 days to catch the
    generating event. End is period_end + 1 day buffer for eval lag. Falls back
    to wide sentinel bounds if state has malformed/missing timestamps so
    partition pruning still has a usable range.
    """
    try:
        ts_start = _ch_ts((datetime.fromisoformat(state["period_start"]) - timedelta(days=7)).isoformat())
    except (ValueError, TypeError, KeyError):
        ts_start = _ch_ts(_WIDENED_TS_START_SENTINEL)
    try:
        ts_end = _ch_ts((datetime.fromisoformat(state["period_end"]) + timedelta(days=1)).isoformat())
    except (ValueError, TypeError, KeyError):
        ts_end = _ch_ts(_WIDENED_TS_END_SENTINEL)
    return ts_start, ts_end


def _execute_hogql(team_id: int, query_str: str, placeholders: dict | None = None) -> list[list]:
    """Execute a HogQL query against `events` and return results.

    Used by every query in this module that does NOT read the six stripped
    heavy columns (`input`, `output`, `output_choices`, `input_state`,
    `output_state`, `tools`). Sweeping these through the resolver too would
    only buy uniform `ai_query_source` tagging — a deliberate scope choice,
    not load-bearing for the strip-heavy migration.
    """
    from posthog.hogql.parser import parse_select
    from posthog.hogql.query import execute_hogql_query

    from posthog.clickhouse.query_tagging import Product, tags_context
    from posthog.models import Team

    team = Team.objects.get(id=team_id)
    query = parse_select(query_str)

    with tags_context(product=Product.LLM_ANALYTICS):
        result = execute_hogql_query(
            query_type="EvalReportAgent",
            query=query,
            placeholders=placeholders or {},
            team=team,
        )

    return result.results or []


def _execute_hogql_via_ai_events(team: "Team", query_str: str, placeholders: dict | None = None) -> list[list]:
    """Execute a HogQL query written against `posthog.ai_events` with the events-table fallback.

    Use this only for queries that read heavy columns (`input`, `output`,
    `output_choices`, `input_state`, `output_state`, `tools`) — those are
    stripped from `events.properties` post-cutover and only survive in the
    dedicated `ai_events` table. Other queries should keep using
    `_execute_hogql` against `events`.
    """
    from posthog.hogql.parser import parse_select

    from posthog.hogql_queries.ai.ai_table_resolver import execute_with_ai_events_fallback

    query = parse_select(query_str)

    # `execute_with_ai_events_fallback` wraps its own
    # `tags_context(product=Product.LLM_ANALYTICS)` internally; no need to
    # double-wrap here.
    result = execute_with_ai_events_fallback(
        query=query,
        placeholders=placeholders or {},
        team=team,
        query_type="EvalReportAgent",
    )

    return result.results or []


def _fetch_period_counts(
    team_id: int, evaluation_id: str, ts_start: datetime, ts_end: datetime
) -> tuple[int, int, int, int]:
    """Fetch pass/fail/NA/total counts for a single time window.

    Returns (pass_count, fail_count, na_count, total).
    """
    rows = _execute_hogql(
        team_id,
        """
        SELECT
            countIf(properties.$ai_evaluation_result = true AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as pass_count,
            countIf(properties.$ai_evaluation_result = false AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as fail_count,
            countIf(properties.$ai_evaluation_applicable = false) as na_count,
            count() as total
        FROM events
        WHERE event = '$ai_evaluation'
            AND properties.$ai_evaluation_id = {evaluation_id}
            AND timestamp >= {ts_start}
            AND timestamp < {ts_end}
        """,
        placeholders={
            "evaluation_id": ast.Constant(value=evaluation_id),
            "ts_start": ast.Constant(value=ts_start),
            "ts_end": ast.Constant(value=ts_end),
        },
    )
    row = rows[0] if rows else [0, 0, 0, 0]
    return int(row[0]), int(row[1]), int(row[2]), int(row[3])


@tool
def get_summary_metrics(
    state: Annotated[dict, InjectedState],
) -> str:
    """Get pass/fail/NA counts and pass rate for the current period AND the previous period.

    Returns current and previous period statistics for comparison. Call this first
    to understand the baseline. Note: these numbers are also computed mechanically
    after you finish and attached to the report as `metrics` — you don't need to
    restate them in your sections, just reference them analytically.
    """
    team_id = state["team_id"]
    evaluation_id = state["evaluation_id"]
    ts_start = _ch_ts(state["period_start"])
    ts_end = _ch_ts(state["period_end"])
    ts_prev_start = _ch_ts(state["previous_period_start"])

    pass_count, fail_count, na_count, total = _fetch_period_counts(team_id, evaluation_id, ts_start, ts_end)
    prev_pass, prev_fail, prev_na, prev_total = _fetch_period_counts(team_id, evaluation_id, ts_prev_start, ts_start)

    applicable = pass_count + fail_count
    pass_rate = round(pass_count / applicable * 100, 2) if applicable > 0 else 0.0
    prev_applicable = prev_pass + prev_fail
    previous_pass_rate = round(prev_pass / prev_applicable * 100, 2) if prev_applicable > 0 else None

    result = {
        "current_period": {
            "total_runs": total,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "na_count": na_count,
            "pass_rate": pass_rate,
        },
        "previous_period": {
            "total_runs": prev_total,
            "pass_count": prev_pass,
            "fail_count": prev_fail,
            "na_count": prev_na,
            "pass_rate": previous_pass_rate,
        },
    }
    return json.dumps(result, indent=2)


@tool
def get_pass_rate_over_time(
    state: Annotated[dict, InjectedState],
    bucket: str = "hour",
) -> str:
    """Get time-series pass rate data bucketed by hour or day.

    Use this to spot trends, anomalies, or degradations over the report period.

    Args:
        bucket: Time bucket size - "hour" or "day" (default "hour")
    """
    team_id = state["team_id"]
    evaluation_id = state["evaluation_id"]
    ts_start = _ch_ts(state["period_start"])
    ts_end = _ch_ts(state["period_end"])

    # Whitelisted truncation function — `bucket` is an LLM-controlled arg, so pick
    # from a fixed set rather than interpolating arbitrary identifiers into SQL.
    trunc_fn = "toStartOfHour" if bucket == "hour" else "toStartOfDay"

    rows = _execute_hogql(
        team_id,
        f"""
        SELECT
            {trunc_fn}(timestamp) as bucket,
            countIf(properties.$ai_evaluation_result = true AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as pass_count,
            countIf(properties.$ai_evaluation_result = false AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as fail_count,
            count() as total
        FROM events
        WHERE event = '$ai_evaluation'
            AND properties.$ai_evaluation_id = {{evaluation_id}}
            AND timestamp >= {{ts_start}}
            AND timestamp < {{ts_end}}
        GROUP BY bucket
        ORDER BY bucket
        """,
        placeholders={
            "evaluation_id": ast.Constant(value=evaluation_id),
            "ts_start": ast.Constant(value=ts_start),
            "ts_end": ast.Constant(value=ts_end),
        },
    )

    result = []
    for row in rows:
        passes = int(row[1])
        fails = int(row[2])
        applicable = passes + fails
        result.append(
            {
                "bucket": str(row[0]),
                "pass_count": passes,
                "fail_count": fails,
                "total": int(row[3]),
                "pass_rate": round(passes / applicable * 100, 2) if applicable > 0 else None,
            }
        )

    return json.dumps(result, indent=2)


_LIST_ALL_MAX_RESULTS = 500


@tool
def list_all_eval_results(
    state: Annotated[dict, InjectedState],
    max_reasoning_length: int = 80,
) -> str:
    """Get a compact overview of evaluation results in the period.

    Returns up to 500 results as condensed rows: verdict, generation_id, and
    truncated reasoning. When there are more than 500 results, returns a random
    sample. Use this as your first scan to spot patterns before drilling into
    specific examples with sample_generation_details.

    Args:
        max_reasoning_length: Truncate reasoning strings to this many characters (default 80)
    """
    team_id = state["team_id"]
    evaluation_id = state["evaluation_id"]
    ts_start = _ch_ts(state["period_start"])
    ts_end = _ch_ts(state["period_end"])

    shared_placeholders = {
        "evaluation_id": ast.Constant(value=evaluation_id),
        "ts_start": ast.Constant(value=ts_start),
        "ts_end": ast.Constant(value=ts_end),
    }

    # First get total count to know if we need to sample.
    count_rows = _execute_hogql(
        team_id,
        """
        SELECT count() as cnt
        FROM events
        WHERE event = '$ai_evaluation'
            AND properties.$ai_evaluation_id = {evaluation_id}
            AND timestamp >= {ts_start}
            AND timestamp < {ts_end}
        """,
        placeholders=shared_placeholders,
    )
    total_count = int(count_rows[0][0]) if count_rows else 0
    is_sampled = total_count > _LIST_ALL_MAX_RESULTS

    # Whitelisted order/limit fragments — no user input flows into these.
    order_clause = "ORDER BY rand()" if is_sampled else "ORDER BY timestamp ASC"
    limit_clause = f"LIMIT {_LIST_ALL_MAX_RESULTS}" if is_sampled else ""

    rows = _execute_hogql(
        team_id,
        f"""
        SELECT
            properties.$ai_target_event_id as generation_id,
            properties.$ai_evaluation_result as result,
            properties.$ai_evaluation_applicable as applicable,
            properties.$ai_evaluation_reasoning as reasoning
        FROM events
        WHERE event = '$ai_evaluation'
            AND properties.$ai_evaluation_id = {{evaluation_id}}
            AND timestamp >= {{ts_start}}
            AND timestamp < {{ts_end}}
        {order_clause}
        {limit_clause}
        """,
        placeholders=shared_placeholders,
    )

    max_reasoning_length = min(max(20, max_reasoning_length), 200)
    lines = []
    for row in rows:
        gen_id = str(row[0]) if row[0] else "?"
        applicable = row[2]
        if applicable is False:
            verdict = "na"
        elif row[1] is True:
            verdict = "pass"
        elif row[1] is False:
            verdict = "fail"
        else:
            verdict = "?"
        reasoning = (row[3] or "")[:max_reasoning_length]
        if row[3] and len(row[3]) > max_reasoning_length:
            reasoning += "..."
        lines.append(f"{verdict} | {gen_id} | {reasoning}")

    if is_sampled:
        header = f"Total: {total_count} results (showing random sample of {len(lines)})\n"
    else:
        header = f"Total: {len(lines)} results\n"
    return header + "\n".join(lines)


@tool
def sample_eval_results(
    state: Annotated[dict, InjectedState],
    filter: str = "all",
    limit: int = 50,
) -> str:
    """Sample evaluation runs with generation_id, result, and reasoning.

    Call multiple times with different filters to understand patterns.

    Args:
        filter: "all", "pass", "fail", or "na"
        limit: Maximum number of results to return (default 50)
    """
    limit = min(max(1, limit), 500)
    team_id = state["team_id"]
    evaluation_id = state["evaluation_id"]
    ts_start = _ch_ts(state["period_start"])
    ts_end = _ch_ts(state["period_end"])

    # Whitelisted filter fragment — `filter` is an LLM-controlled arg; pick
    # from a fixed set rather than interpolating arbitrary SQL.
    filter_clause = ""
    if filter == "pass":
        filter_clause = "AND properties.$ai_evaluation_result = true AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)"
    elif filter == "fail":
        filter_clause = "AND properties.$ai_evaluation_result = false AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)"
    elif filter == "na":
        filter_clause = "AND properties.$ai_evaluation_applicable = false"

    rows = _execute_hogql(
        team_id,
        f"""
        SELECT
            properties.$ai_target_event_id as generation_id,
            properties.$ai_evaluation_result as result,
            properties.$ai_evaluation_reasoning as reasoning,
            properties.$ai_evaluation_applicable as applicable
        FROM events
        WHERE event = '$ai_evaluation'
            AND properties.$ai_evaluation_id = {{evaluation_id}}
            AND timestamp >= {{ts_start}}
            AND timestamp < {{ts_end}}
            {filter_clause}
        ORDER BY timestamp DESC
        LIMIT {{limit}}
        """,
        placeholders={
            "evaluation_id": ast.Constant(value=evaluation_id),
            "ts_start": ast.Constant(value=ts_start),
            "ts_end": ast.Constant(value=ts_end),
            "limit": ast.Constant(value=limit),
        },
    )

    result = []
    for row in rows:
        applicable = row[3]
        eval_result = None if applicable is False else row[1]
        result.append(
            {
                "generation_id": str(row[0]) if row[0] else "",
                "result": eval_result,
                "reasoning": row[2] or "",
            }
        )

    return json.dumps(result, indent=2)


@tool
def sample_generation_details(
    state: Annotated[dict, InjectedState],
    generation_ids: list[str],
) -> str:
    """Get full $ai_generation event data for specific generations.

    Returns input, output, model, tokens, AND trace_id for verification before
    citing in the report. **Always call this before add_citation** so you have
    the trace_id to pass in.

    Args:
        generation_ids: List of generation IDs to look up (max 20)
    """
    if not generation_ids:
        return json.dumps([])

    # Strict UUID validation: generation IDs originate from the LLM and may relay
    # values from $ai_target_event_id which is set by user instrumentation. Reject
    # anything that isn't a canonical UUID before passing into HogQL.
    ids_to_fetch = [gid for gid in generation_ids[:20] if _UUID_RE.fullmatch(gid)]
    if not ids_to_fetch:
        return json.dumps([])

    # generation_ids from sample_eval_results are $ai_target_event_id values,
    # which reference the event UUID of $ai_generation events (not $ai_generation_id
    # which the SDK doesn't set). Match on the event uuid column.
    # $ai_output is empty for chat-format SDK calls (most OpenAI/Anthropic).
    # The actual content lives in $ai_output_choices. Use COALESCE to fall back.
    # Reads heavy `input` / `output` / `output_choices` / `input_state` /
    # `output_state` — must go through ai_events (post-strip those are NULL on
    # events). On the events fallback the column rewriter rewrites these
    # native columns back to `properties.$ai_*`, so the coalesce semantics are
    # preserved on both branches.
    from posthog.hogql_queries.ai.trace_id_resolver import resolve_trace_ids_for_generation_uuids
    from posthog.models import Team

    team = Team.objects.get(id=state["team_id"])
    ts_start, ts_end = _widened_ts_window(state)
    trace_id_by_uuid = resolve_trace_ids_for_generation_uuids(
        team=team,
        generation_uuids=ids_to_fetch,
        ts_start=ts_start,
        ts_end=ts_end,
        query_type="EvalReportAgentTraceIdResolve",
    )
    trace_ids = sorted({tid for tid in trace_id_by_uuid.values() if tid})
    if not trace_ids:
        return json.dumps([])

    rows = _execute_hogql_via_ai_events(
        team,
        """
        SELECT
            toString(uuid) as generation_id,
            model,
            input,
            coalesce(
                nullIf(output, ''),
                output_choices
            ) as output,
            input_tokens,
            output_tokens,
            trace_id,
            is_error,
            error,
            properties.$ai_tools_called as tools_called,
            properties.$ai_tool_call_count as tool_call_count,
            input_state,
            output_state
        FROM posthog.ai_events AS ai_events
        WHERE event = '$ai_generation'
            AND trace_id IN {trace_ids}
            AND toString(uuid) IN {ids}
        LIMIT {limit}
        """,
        placeholders={
            "ids": ast.Array(exprs=[ast.Constant(value=gid) for gid in ids_to_fetch]),
            "trace_ids": ast.Array(exprs=[ast.Constant(value=tid) for tid in trace_ids]),
            "limit": ast.Constant(value=len(ids_to_fetch)),
        },
    )

    result = []
    for row in rows:
        input_text = str(row[2])[:500] if row[2] else ""
        output_text = str(row[3])[:500] if row[3] else ""
        entry: dict = {
            "generation_id": str(row[0]) if row[0] else "",
            "model": str(row[1]) if row[1] else "",
            "input_preview": input_text,
            "output_preview": output_text,
            "input_tokens": row[4],
            "output_tokens": row[5],
            "trace_id": str(row[6]) if row[6] else "",
        }
        if row[7]:  # is_error
            error_text = str(row[8])[:500] if row[8] else ""
            entry["is_error"] = True
            entry["error_preview"] = error_text
        if row[9]:  # tools_called
            entry["tools_called"] = str(row[9])
            entry["tool_call_count"] = row[10]
        if row[11]:  # input_state
            entry["input_state_preview"] = str(row[11])[:500]
        if row[12]:  # output_state
            entry["output_state_preview"] = str(row[12])[:500]
        result.append(entry)

    return json.dumps(result, indent=2)


@tool
def get_generation_detail(
    state: Annotated[dict, InjectedState],
    generation_id: str,
) -> str:
    """Get full details for a single generation — no truncation.

    Use this to deep-dive into a specific generation when the 500-char preview
    from sample_generation_details isn't enough to understand what happened.
    Returns the complete input, output, all properties, and eval results.

    Args:
        generation_id: The generation event UUID to look up
    """
    team_id = state["team_id"]

    if not _UUID_RE.fullmatch(generation_id):
        return json.dumps({"error": "Invalid generation ID format"})

    from posthog.hogql_queries.ai.trace_id_resolver import resolve_trace_ids_for_generation_uuids
    from posthog.models import Team

    team = Team.objects.get(id=team_id)
    ts_start, ts_end = _widened_ts_window(state)
    shared_placeholders = {
        "generation_id": ast.Constant(value=generation_id),
        "ts_start": ast.Constant(value=ts_start),
        "ts_end": ast.Constant(value=ts_end),
    }

    trace_id_by_uuid = resolve_trace_ids_for_generation_uuids(
        team=team,
        generation_uuids=[generation_id],
        ts_start=ts_start,
        ts_end=ts_end,
        query_type="EvalReportAgentTraceIdResolve",
    )
    trace_id = trace_id_by_uuid.get(generation_id)
    if not trace_id:
        return json.dumps({"error": f"Generation {generation_id} not found"})

    gen_placeholders = {
        "generation_id": shared_placeholders["generation_id"],
        "trace_id": ast.Constant(value=trace_id),
    }

    # Full generation event data — heavy `input` / `output` / `output_choices` /
    # `tools` / `input_state` / `output_state` only survive on ai_events.
    gen_rows = _execute_hogql_via_ai_events(
        team,
        """
        SELECT
            toString(uuid) as generation_id,
            model,
            provider,
            input,
            coalesce(
                nullIf(output, ''),
                output_choices
            ) as output,
            input_tokens,
            output_tokens,
            total_cost_usd as cost,
            latency,
            trace_id,
            properties.$ai_base_url as base_url,
            timestamp,
            is_error,
            error,
            properties.$ai_tools_called as tools_called,
            properties.$ai_tool_call_count as tool_call_count,
            tools as tools_available,
            input_state,
            output_state
        FROM posthog.ai_events AS ai_events
        WHERE event = '$ai_generation'
            AND trace_id = {trace_id}
            AND toString(uuid) = {generation_id}
        LIMIT 1
        """,
        placeholders=gen_placeholders,
    )

    if not gen_rows:
        return json.dumps({"error": f"Generation {generation_id} not found"})

    row = gen_rows[0]

    # Also fetch eval results for this generation
    eval_rows = _execute_hogql(
        team_id,
        """
        SELECT
            properties.$ai_evaluation_id as eval_id,
            properties.$ai_evaluation_result as result,
            properties.$ai_evaluation_reasoning as reasoning,
            properties.$ai_evaluation_applicable as applicable
        FROM events
        WHERE event = '$ai_evaluation'
            AND properties.$ai_target_event_id = {generation_id}
            AND timestamp >= {ts_start}
            AND timestamp < {ts_end}
        ORDER BY timestamp DESC
        LIMIT 20
        """,
        placeholders=shared_placeholders,
    )

    evals = []
    for er in eval_rows:
        applicable = er[3]
        evals.append(
            {
                "evaluation_id": str(er[0]) if er[0] else "",
                "result": None if applicable is False else er[1],
                "reasoning": er[2] or "",
            }
        )

    result: dict = {
        "generation_id": str(row[0]) if row[0] else "",
        "model": str(row[1]) if row[1] else "",
        "provider": str(row[2]) if row[2] else "",
        "input": str(row[3]) if row[3] else "",
        "output": str(row[4]) if row[4] else "",
        "input_tokens": row[5],
        "output_tokens": row[6],
        "cost": row[7],
        "latency": row[8],
        "trace_id": str(row[9]) if row[9] else "",
        "base_url": str(row[10]) if row[10] else "",
        "timestamp": str(row[11]) if row[11] else "",
        "eval_results": evals,
    }
    if row[12]:  # is_error
        result["is_error"] = True
        result["error"] = str(row[13]) if row[13] else ""
    if row[14]:  # tools_called
        result["tools_called"] = str(row[14])
        result["tool_call_count"] = row[15]
    if row[16]:  # tools_available
        result["tools_available"] = str(row[16])
    if row[17]:  # input_state
        result["input_state"] = str(row[17])
    if row[18]:  # output_state
        result["output_state"] = str(row[18])

    return json.dumps(result, indent=2)


@tool
def get_generation_text_repr(
    state: Annotated[dict, InjectedState],
    generation_id: str,
) -> str:
    """Get a formatted text representation of a generation event.

    Returns a human-readable view with tools, input messages, output messages,
    and errors rendered in a structured format — the same view used in the
    PostHog UI summarization panel. Use this when raw JSON from
    get_generation_detail is hard to interpret (e.g. deeply nested chat
    messages, complex tool calls, or structured error objects).

    Args:
        generation_id: The generation event UUID to look up
    """
    from posthog.hogql_queries.ai.trace_id_resolver import resolve_trace_ids_for_generation_uuids
    from posthog.models import Team

    from products.llm_analytics.backend.text_repr.formatters import format_event_text_repr_from_ai_events_row

    if not _UUID_RE.fullmatch(generation_id):
        return json.dumps({"error": "Invalid generation ID format"})

    team = Team.objects.get(id=state["team_id"])
    ts_start, ts_end = _widened_ts_window(state)

    trace_id_by_uuid = resolve_trace_ids_for_generation_uuids(
        team=team,
        generation_uuids=[generation_id],
        ts_start=ts_start,
        ts_end=ts_end,
        query_type="EvalReportAgentTraceIdResolve",
    )
    trace_id = trace_id_by_uuid.get(generation_id)
    if not trace_id:
        return json.dumps({"error": f"Generation {generation_id} not found"})

    rows = _execute_hogql_via_ai_events(
        team,
        """
        SELECT
            toString(uuid) as uuid,
            event,
            timestamp,
            input,
            output,
            output_choices,
            tools,
            is_error,
            error
        FROM posthog.ai_events AS ai_events
        WHERE event = '$ai_generation'
            AND trace_id = {trace_id}
            AND toString(uuid) = {generation_id}
        LIMIT 1
        """,
        placeholders={
            "generation_id": ast.Constant(value=generation_id),
            "trace_id": ast.Constant(value=trace_id),
        },
    )

    if not rows:
        return json.dumps({"error": f"Generation {generation_id} not found"})

    row = rows[0]
    text_repr = format_event_text_repr_from_ai_events_row(
        {
            "uuid": row[0],
            "event": row[1],
            "timestamp": row[2],
            "input": row[3],
            "output": row[4],
            "output_choices": row[5],
            "tools": row[6],
            "is_error": row[7],
            "error": row[8],
        }
    )

    # Cap at 10k chars to avoid blowing up context
    if len(text_repr) > 10_000:
        text_repr = text_repr[:10_000] + "\n\n... (truncated)"

    return text_repr


@tool
def list_recent_report_runs(
    state: Annotated[dict, InjectedState],
    since_days: int = 30,
    limit: int = 20,
) -> str:
    """List metadata for previous report runs of this evaluation.

    Returns a compact index: run_id, period, title, pass rate, total runs.
    No full content — use this to discover which past runs look interesting,
    then call `get_report_run(run_id)` to pull the full narrative for the ones
    worth reading. This two-step pattern keeps context small when scanning a
    long history.

    Args:
        since_days: Only include runs whose period ends within the last N days (default 30, max 365)
        limit: Maximum number of runs to return (default 20, max 200)
    """
    from products.llm_analytics.backend.models.evaluation_reports import EvaluationReportRun

    since_days = min(max(1, since_days), 365)
    limit = min(max(1, limit), 200)
    evaluation_id = state["evaluation_id"]

    try:
        period_start = datetime.fromisoformat(state["period_start"])
    except (ValueError, TypeError, KeyError):
        period_start = datetime.now(tz=UTC)

    since = period_start - timedelta(days=since_days)

    runs = EvaluationReportRun.objects.filter(
        report__evaluation_id=evaluation_id,
        # `lte` (not `lt`) so the immediately preceding back-to-back run — the most
        # useful one for delta analysis — is included. The current run hasn't been
        # stored yet at tool-call time, so this can't accidentally pull it in.
        period_end__lte=period_start,
        period_end__gte=since,
    ).order_by("-period_end")[:limit]

    result = []
    for run in runs:
        content = run.content if isinstance(run.content, dict) else {}
        metadata = run.metadata if isinstance(run.metadata, dict) else {}
        # Metrics live in `content.metrics` per the agent output contract; a parallel
        # `metadata` mirror is maintained in the store activity for legacy consumers.
        # Prefer content so this tool stays correct even if the mirror is removed.
        metrics = content.get("metrics", {}) if isinstance(content.get("metrics"), dict) else {}
        result.append(
            {
                "run_id": str(run.id),
                "period_start": str(run.period_start),
                "period_end": str(run.period_end),
                "title": content.get("title", ""),
                "pass_rate": metrics.get("pass_rate", metadata.get("pass_rate")),
                "total_runs": metrics.get("total_runs", metadata.get("total_runs")),
                "delivery_status": run.delivery_status,
            }
        )

    return json.dumps(result, indent=2, default=str)


@tool
def get_report_run(
    state: Annotated[dict, InjectedState],
    run_id: str,
) -> str:
    """Fetch the full content + metadata for a single past report run.

    Use after `list_recent_report_runs` to drill into a specific run that looks
    relevant for delta analysis. Returns the full serialized report (title,
    sections, citations, metrics).

    Args:
        run_id: The report run UUID, from list_recent_report_runs.
    """
    from products.llm_analytics.backend.models.evaluation_reports import EvaluationReportRun

    if not _UUID_RE.fullmatch(run_id or ""):
        return json.dumps({"error": "Invalid run_id format"})

    # Scope to the current evaluation so the agent can't read runs from another eval.
    evaluation_id = state["evaluation_id"]
    try:
        run = EvaluationReportRun.objects.get(id=run_id, report__evaluation_id=evaluation_id)
    except EvaluationReportRun.DoesNotExist:
        return json.dumps({"error": f"Run {run_id} not found for this evaluation"})

    return json.dumps(
        {
            "run_id": str(run.id),
            "period_start": str(run.period_start),
            "period_end": str(run.period_end),
            "content": run.content,
            "metadata": run.metadata,
            "delivery_status": run.delivery_status,
        },
        indent=2,
        default=str,
    )


@tool
def get_top_failure_reasons(
    state: Annotated[dict, InjectedState],
    limit: int = 10,
) -> str:
    """Get grouped failure reasoning strings for quick failure mode overview.

    Args:
        limit: Maximum number of failure reason groups to return (default 10)
    """
    limit = min(max(1, limit), 500)
    team_id = state["team_id"]
    evaluation_id = state["evaluation_id"]
    ts_start = _ch_ts(state["period_start"])
    ts_end = _ch_ts(state["period_end"])

    rows = _execute_hogql(
        team_id,
        """
        SELECT
            properties.$ai_evaluation_reasoning as reasoning,
            count() as cnt
        FROM events
        WHERE event = '$ai_evaluation'
            AND properties.$ai_evaluation_id = {evaluation_id}
            AND properties.$ai_evaluation_result = false
            AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)
            AND timestamp >= {ts_start}
            AND timestamp < {ts_end}
        GROUP BY reasoning
        ORDER BY cnt DESC
        LIMIT {limit}
        """,
        placeholders={
            "evaluation_id": ast.Constant(value=evaluation_id),
            "ts_start": ast.Constant(value=ts_start),
            "ts_end": ast.Constant(value=ts_end),
            "limit": ast.Constant(value=limit),
        },
    )

    result = []
    for row in rows:
        result.append(
            {
                "reasoning": row[0] or "",
                "count": int(row[1]),
            }
        )

    return json.dumps(result, indent=2)


@tool
def set_title(
    state: Annotated[dict, InjectedState],
    title: str,
) -> str:
    """Set the report's top-level punchline title. REQUIRED — call exactly once.

    The title is the single most scannable surface — it shows up in email subjects,
    Slack headers, and the Reports tab preview row. Write a specific, scannable
    headline that tells the reader the main finding at a glance. Avoid generic
    titles like "Evaluation report" or "Analysis summary".

    Good examples:
      - "Pass rate steady at 94%, dip at 14:00 UTC bucket"
      - "Volume dropped to zero — likely pipeline issue"
      - "Cost regression: gpt-5-mini 3x more expensive than last week"

    Args:
        title: One-line headline (plain text, no markdown). Keep under 120 chars.
    """
    clean = (title or "").strip()
    if not clean:
        return "Error: title cannot be empty"
    # Clip to a sensible max so it doesn't blow up email subject lines.
    if len(clean) > 200:
        clean = clean[:197] + "..."
    state["report"].title = clean
    return f"Title set: {clean!r}"


@tool
def add_section(
    state: Annotated[dict, InjectedState],
    title: str,
    content: str,
) -> str:
    """Append a titled markdown section to the report.

    You may call this 1 to {max_sections} times. Prefer fewer, substantive sections
    over many with filler. By convention, the FIRST section you add should be the
    executive summary / TL;DR — it's what lands in the Slack main message.

    Don't restate raw counts like "total_runs: 53, pass_count: 50" in prose — the
    viewer renders a separate metrics block. Focus on analysis, comparisons,
    hypotheses, and concrete recommendations.

    Reference specific traces by calling add_citation separately with the
    generation_id + trace_id from sample_generation_details.

    Args:
        title: Short title for this section (e.g. "Summary", "Volume drop at 14:00").
            No markdown, keep it under 100 chars.
        content: Markdown body of the section. Headers, lists, tables, and bold
            are all supported.
    """
    clean_title = (title or "").strip()
    clean_content = (content or "").strip()
    if not clean_title:
        return "Error: section title cannot be empty"
    if not clean_content:
        return "Error: section content cannot be empty"
    if len(state["report"].sections) >= MAX_REPORT_SECTIONS:
        return (
            f"Error: maximum of {MAX_REPORT_SECTIONS} sections reached. "
            "Merge your content into existing sections rather than fragmenting further."
        )
    state["report"].sections.append(ReportSection(title=clean_title, content=clean_content))
    return f"Section {len(state['report'].sections)}/{MAX_REPORT_SECTIONS} added: {clean_title!r} ({len(clean_content)} chars)"


# Make the cap visible in the docstring above (the `{max_sections}` placeholder).
add_section.__doc__ = (add_section.__doc__ or "").replace("{max_sections}", str(MAX_REPORT_SECTIONS))


@tool
def add_citation(
    state: Annotated[dict, InjectedState],
    generation_id: str,
    trace_id: str,
    reason: str,
) -> str:
    """Cite a specific trace that supports a finding in the report.

    Citations are structured references that downstream consumers (signals, inbox,
    coding agents) can filter on without parsing prose. Always call
    sample_generation_details first to verify the generation exists and to get
    its trace_id.

    Args:
        generation_id: UUID of the $ai_generation event.
        trace_id: UUID of the trace that contains the generation.
        reason: Short free-form reason for the citation, e.g. "high_cost",
            "refusal", "regression_at_14:00", "empty_output".
    """
    if not _UUID_RE.fullmatch(generation_id or ""):
        return f"Error: generation_id {generation_id!r} is not a canonical UUID"
    if not _UUID_RE.fullmatch(trace_id or ""):
        return f"Error: trace_id {trace_id!r} is not a canonical UUID"
    clean_reason = (reason or "").strip()[:200]
    state["report"].citations.append(Citation(generation_id=generation_id, trace_id=trace_id, reason=clean_reason))
    return f"Citation {len(state['report'].citations)} added: {generation_id[:8]}... ({clean_reason!r})"


EVAL_REPORT_TOOLS = [
    # Query tools (read-only, agent calls as needed)
    get_summary_metrics,
    get_pass_rate_over_time,
    list_all_eval_results,
    sample_eval_results,
    sample_generation_details,
    get_generation_detail,
    get_generation_text_repr,
    list_recent_report_runs,
    get_report_run,
    get_top_failure_reasons,
    # Output tools (mutate state["report"])
    set_title,
    add_section,
    add_citation,
]
