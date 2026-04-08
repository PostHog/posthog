"""Tool definitions for the evaluation report agent.

Uses LangGraph's InjectedState pattern so tools can access graph state directly.
All query tools hit ClickHouse live via HogQL since the dataset is too large/variable
to pre-load. Output tools mutate `state["report"]` (an EvalReportContent instance)
via list append / attribute set — in-place mutations propagate back through
InjectedState, but whole-key replacement does not.
"""

import re
import json
from datetime import UTC
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import MAX_REPORT_SECTIONS, Citation, ReportSection

# Strict UUID match for validating IDs before string-interpolating into HogQL
# and before storing in Citation. Generation IDs reach this code from the LLM,
# which can relay arbitrary `$ai_target_event_id` property values set by user
# instrumentation. Trace IDs have the same trust boundary.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _ch_ts(iso_str: str) -> str:
    """Convert an ISO-8601 timestamp to a ClickHouse-compatible format.

    ClickHouse DateTime64 can't parse 'T' separator or '+00:00' timezone directly.
    Converts '2026-03-12T10:05:48.034000+00:00' → '2026-03-12 10:05:48.034000'.
    """
    from datetime import datetime

    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def _execute_hogql(team_id: int, query_str: str, placeholders: dict | None = None) -> list[list]:
    """Execute a HogQL query and return results."""
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
    period_start = state["period_start"]
    period_end = state["period_end"]
    previous_period_start = state["previous_period_start"]

    ts_start = _ch_ts(period_start)
    ts_end = _ch_ts(period_end)
    ts_prev_start = _ch_ts(previous_period_start)

    current_rows = _execute_hogql(
        team_id,
        f"""
        SELECT
            countIf(properties.$ai_evaluation_result = true AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as pass_count,
            countIf(properties.$ai_evaluation_result = false AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as fail_count,
            countIf(properties.$ai_evaluation_applicable = false) as na_count,
            count() as total
        FROM events
        WHERE event = '$ai_evaluation'
            AND properties.$ai_evaluation_id = '{evaluation_id}'
            AND timestamp >= '{ts_start}'
            AND timestamp < '{ts_end}'
        """,
    )

    previous_rows = _execute_hogql(
        team_id,
        f"""
        SELECT
            countIf(properties.$ai_evaluation_result = true AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as pass_count,
            countIf(properties.$ai_evaluation_result = false AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as fail_count,
            countIf(properties.$ai_evaluation_applicable = false) as na_count,
            count() as total
        FROM events
        WHERE event = '$ai_evaluation'
            AND properties.$ai_evaluation_id = '{evaluation_id}'
            AND timestamp >= '{ts_prev_start}'
            AND timestamp < '{ts_start}'
        """,
    )

    current = current_rows[0] if current_rows else [0, 0, 0, 0]
    previous = previous_rows[0] if previous_rows else [0, 0, 0, 0]

    pass_count = int(current[0])
    fail_count = int(current[1])
    na_count = int(current[2])
    total = int(current[3])
    applicable = pass_count + fail_count
    pass_rate = round(pass_count / applicable * 100, 2) if applicable > 0 else 0.0

    prev_pass = int(previous[0])
    prev_fail = int(previous[1])
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
            "total_runs": int(previous[3]),
            "pass_count": prev_pass,
            "fail_count": prev_fail,
            "na_count": int(previous[2]),
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
            AND properties.$ai_evaluation_id = '{evaluation_id}'
            AND timestamp >= '{ts_start}'
            AND timestamp < '{ts_end}'
        GROUP BY bucket
        ORDER BY bucket
        """,
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
    team_id = state["team_id"]
    evaluation_id = state["evaluation_id"]
    ts_start = _ch_ts(state["period_start"])
    ts_end = _ch_ts(state["period_end"])

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
            AND properties.$ai_evaluation_id = '{evaluation_id}'
            AND timestamp >= '{ts_start}'
            AND timestamp < '{ts_end}'
            {filter_clause}
        ORDER BY timestamp DESC
        LIMIT {limit}
        """,
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
    team_id = state["team_id"]

    if not generation_ids:
        return json.dumps([])

    # Strict UUID validation: generation IDs originate from the LLM and may relay
    # values from $ai_target_event_id which is set by user instrumentation. Reject
    # anything that isn't a canonical UUID before interpolating into HogQL.
    ids_to_fetch = [gid for gid in generation_ids[:20] if _UUID_RE.fullmatch(gid)]
    if not ids_to_fetch:
        return json.dumps([])
    ids_str = ", ".join(f"'{gid}'" for gid in ids_to_fetch)

    rows = _execute_hogql(
        team_id,
        f"""
        SELECT
            properties.$ai_generation_id as generation_id,
            properties.$ai_model as model,
            properties.$ai_input as input,
            properties.$ai_output as output,
            properties.$ai_input_tokens as input_tokens,
            properties.$ai_output_tokens as output_tokens,
            properties.$ai_trace_id as trace_id
        FROM events
        WHERE event = '$ai_generation'
            AND properties.$ai_generation_id IN ({ids_str})
        LIMIT {len(ids_to_fetch)}
        """,
    )

    result = []
    for row in rows:
        input_text = str(row[2])[:500] if row[2] else ""
        output_text = str(row[3])[:500] if row[3] else ""
        result.append(
            {
                "generation_id": str(row[0]) if row[0] else "",
                "model": str(row[1]) if row[1] else "",
                "input_preview": input_text,
                "output_preview": output_text,
                "input_tokens": row[4],
                "output_tokens": row[5],
                "trace_id": str(row[6]) if row[6] else "",
            }
        )

    return json.dumps(result, indent=2)


@tool
def get_recent_reports(
    state: Annotated[dict, InjectedState],
    limit: int = 3,
) -> str:
    """Get content from previous evaluation report runs for delta analysis.

    Helps identify what has changed since the last report.

    Args:
        limit: Number of recent reports to fetch (default 3)
    """
    from products.llm_analytics.backend.models.evaluation_reports import EvaluationReportRun

    evaluation_id = state["evaluation_id"]
    period_start = state["period_start"]

    recent_runs = EvaluationReportRun.objects.filter(
        report__evaluation_id=evaluation_id,
        period_end__lt=period_start,
    ).order_by("-created_at")[:limit]

    result = []
    for run in recent_runs:
        result.append(
            {
                "period_start": str(run.period_start),
                "period_end": str(run.period_end),
                "content": run.content,
                "metadata": run.metadata,
            }
        )

    return json.dumps(result, indent=2, default=str)


@tool
def get_top_failure_reasons(
    state: Annotated[dict, InjectedState],
    limit: int = 10,
) -> str:
    """Get grouped failure reasoning strings for quick failure mode overview.

    Args:
        limit: Maximum number of failure reason groups to return (default 10)
    """
    team_id = state["team_id"]
    evaluation_id = state["evaluation_id"]
    ts_start = _ch_ts(state["period_start"])
    ts_end = _ch_ts(state["period_end"])

    rows = _execute_hogql(
        team_id,
        f"""
        SELECT
            properties.$ai_evaluation_reasoning as reasoning,
            count() as cnt
        FROM events
        WHERE event = '$ai_evaluation'
            AND properties.$ai_evaluation_id = '{evaluation_id}'
            AND properties.$ai_evaluation_result = false
            AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)
            AND timestamp >= '{ts_start}'
            AND timestamp < '{ts_end}'
        GROUP BY reasoning
        ORDER BY cnt DESC
        LIMIT {limit}
        """,
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
    sample_eval_results,
    sample_generation_details,
    get_recent_reports,
    get_top_failure_reasons,
    # Output tools (mutate state["report"])
    set_title,
    add_section,
    add_citation,
]
