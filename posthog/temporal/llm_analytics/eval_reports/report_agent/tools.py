"""Tool definitions for the evaluation report agent.

Uses LangGraph's InjectedState pattern so tools can access graph state directly.
All tools query ClickHouse live via HogQL since the dataset is too large/variable to pre-load.
"""

import re
import json
from datetime import UTC
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import (
    REPORT_SECTIONS,
    EvalReportMetadata,
    ReportSection,
)

UUID_PATTERN = re.compile(r"`([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`")


def _ch_ts(iso_str: str) -> str:
    """Convert an ISO-8601 timestamp to a ClickHouse-compatible format.

    ClickHouse DateTime64 can't parse 'T' separator or '+00:00' timezone directly.
    Converts '2026-03-12T10:05:48.034000+00:00' → '2026-03-12 10:05:48.034000'.
    """
    from datetime import datetime

    dt = datetime.fromisoformat(iso_str)
    # Ensure UTC
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

    Sets computed_metadata on state. Always call this first to understand the baseline.
    Returns current and previous period statistics for comparison.
    """
    team_id = state["team_id"]
    evaluation_id = state["evaluation_id"]
    period_start = state["period_start"]
    period_end = state["period_end"]
    previous_period_start = state["previous_period_start"]

    ts_start = _ch_ts(period_start)
    ts_end = _ch_ts(period_end)
    ts_prev_start = _ch_ts(previous_period_start)

    # Current period
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

    # Previous period
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

    metadata = EvalReportMetadata(
        total_runs=total,
        pass_count=pass_count,
        fail_count=fail_count,
        na_count=na_count,
        pass_rate=pass_rate,
        previous_pass_rate=previous_pass_rate,
    )
    state["computed_metadata"] = metadata

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

    Returns input, output, model, tokens for verification before citing in the report.

    Args:
        generation_ids: List of generation IDs to look up (max 20)
    """
    team_id = state["team_id"]

    if not generation_ids:
        return json.dumps([])

    ids_to_fetch = generation_ids[:20]
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
def set_report_section(
    state: Annotated[dict, InjectedState],
    section: str,
    content: str,
) -> str:
    """Write a section of the report.

    Auto-extracts generation IDs referenced in backticks for linking in delivery.

    Args:
        section: Section name. One of: executive_summary, statistics, trend_analysis,
                 failure_patterns, pass_patterns, notable_changes, recommendations, risk_assessment
        content: Markdown content for the section. Reference generation IDs in backticks.
    """
    if section not in REPORT_SECTIONS:
        return f"Invalid section '{section}'. Valid sections: {', '.join(REPORT_SECTIONS)}"

    referenced_ids = UUID_PATTERN.findall(content)

    state["report"][section] = ReportSection(
        content=content,
        referenced_generation_ids=referenced_ids,
    )
    return f"Section '{section}' set ({len(content)} chars, {len(referenced_ids)} generation IDs referenced)"


@tool
def finalize_report(
    state: Annotated[dict, InjectedState],
) -> str:
    """Signal that the report is complete.

    Only call this when you have written all relevant sections.
    """
    written = [s for s in REPORT_SECTIONS if state["report"].get(s) is not None]
    return f"Report finalized with {len(written)} sections: {', '.join(written)}"


EVAL_REPORT_TOOLS = [
    get_summary_metrics,
    get_pass_rate_over_time,
    sample_eval_results,
    sample_generation_details,
    get_recent_reports,
    get_top_failure_reasons,
    set_report_section,
    finalize_report,
]
