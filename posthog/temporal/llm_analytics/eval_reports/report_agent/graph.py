"""LangGraph agent for evaluation report generation using create_react_agent."""

import os
from typing import Any

from django.conf import settings

import structlog
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from posthog.cloud_utils import is_cloud
from posthog.temporal.llm_analytics.eval_reports.report_agent.prompts import EVAL_REPORT_SYSTEM_PROMPT
from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import (
    EvalReportContent,
    EvalReportMetadata,
    ReportSection,
)
from posthog.temporal.llm_analytics.eval_reports.report_agent.state import EvalReportAgentState
from posthog.temporal.llm_analytics.eval_reports.report_agent.tools import EVAL_REPORT_TOOLS

logger = structlog.get_logger(__name__)


def _get_llm(model: str, timeout: float) -> ChatOpenAI:
    """Create an OpenAI chat client for the report agent."""
    if not settings.DEBUG and not is_cloud():
        raise Exception("AI features are only available in PostHog Cloud")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise Exception("OpenAI API key is not configured")

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_retries=2,
    )


def _fill_missing_sections(
    report: dict[str, ReportSection | None],
    metadata: EvalReportMetadata | None,
) -> EvalReportContent:
    """Ensure executive_summary and statistics are present, filling defaults if needed."""
    content = EvalReportContent()

    for section_name, section in report.items():
        if section is not None:
            setattr(content, section_name, section)

    if content.executive_summary is None and metadata is not None:
        trend = ""
        if metadata.previous_pass_rate is not None:
            diff = metadata.pass_rate - metadata.previous_pass_rate
            if diff > 1:
                trend = f" (up from {metadata.previous_pass_rate}%)"
            elif diff < -1:
                trend = f" (down from {metadata.previous_pass_rate}%)"
            else:
                trend = f" (stable vs {metadata.previous_pass_rate}%)"

        content.executive_summary = ReportSection(
            content=f"**Pass rate: {metadata.pass_rate}%**{trend} across {metadata.total_runs} evaluation runs. "
            f"{metadata.pass_count} passed, {metadata.fail_count} failed, {metadata.na_count} N/A.",
        )

    if content.statistics is None and metadata is not None:
        content.statistics = ReportSection(
            content=(
                f"- **Total runs**: {metadata.total_runs}\n"
                f"- **Pass**: {metadata.pass_count} ({metadata.pass_rate}%)\n"
                f"- **Fail**: {metadata.fail_count}\n"
                f"- **N/A**: {metadata.na_count}"
            ),
        )

    return content


def _compute_metadata(
    team_id: int,
    evaluation_id: str,
    period_start: str,
    period_end: str,
    previous_period_start: str,
) -> EvalReportMetadata | None:
    """Compute report metadata directly via HogQL (independent of agent state)."""
    from posthog.temporal.llm_analytics.eval_reports.report_agent.tools import _ch_ts, _execute_hogql

    try:
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
                countIf(properties.$ai_evaluation_result = false AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)) as fail_count
            FROM events
            WHERE event = '$ai_evaluation'
                AND properties.$ai_evaluation_id = '{evaluation_id}'
                AND timestamp >= '{ts_prev_start}'
                AND timestamp < '{ts_start}'
            """,
        )

        current = current_rows[0] if current_rows else [0, 0, 0, 0]
        previous = previous_rows[0] if previous_rows else [0, 0]

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

        return EvalReportMetadata(
            total_runs=total,
            pass_count=pass_count,
            fail_count=fail_count,
            na_count=na_count,
            pass_rate=pass_rate,
            previous_pass_rate=previous_pass_rate,
        )
    except Exception:
        logger.exception("Failed to compute report metadata")
        return None


def run_eval_report_agent(
    team_id: int,
    evaluation_id: str,
    evaluation_name: str,
    evaluation_description: str,
    evaluation_prompt: str,
    evaluation_type: str,
    period_start: str,
    period_end: str,
    previous_period_start: str,
) -> tuple[EvalReportContent, EvalReportMetadata | None]:
    """Run the evaluation report agent and return the generated report.

    Returns:
        Tuple of (EvalReportContent, EvalReportMetadata or None)
    """
    from posthog.temporal.llm_analytics.eval_reports.constants import (
        EVAL_REPORT_AGENT_MODEL,
        EVAL_REPORT_AGENT_RECURSION_LIMIT,
        EVAL_REPORT_AGENT_TIMEOUT,
    )

    llm = _get_llm(EVAL_REPORT_AGENT_MODEL, EVAL_REPORT_AGENT_TIMEOUT)

    description_section = f"Description: {evaluation_description}\n" if evaluation_description else ""
    prompt_section = f"Evaluation prompt/criteria:\n```\n{evaluation_prompt}\n```\n" if evaluation_prompt else ""

    system_prompt = EVAL_REPORT_SYSTEM_PROMPT.format(
        evaluation_name=evaluation_name,
        evaluation_description_section=description_section,
        evaluation_type=evaluation_type,
        evaluation_prompt_section=prompt_section,
        period_start=period_start,
        period_end=period_end,
    )

    agent = create_react_agent(
        model=llm,
        tools=EVAL_REPORT_TOOLS,
        prompt=system_prompt,
        state_schema=EvalReportAgentState,
    )

    initial_state: dict[str, Any] = {
        "messages": [HumanMessage(content="Please generate the evaluation report.")],
        "team_id": team_id,
        "evaluation_id": evaluation_id,
        "evaluation_name": evaluation_name,
        "evaluation_description": evaluation_description,
        "evaluation_prompt": evaluation_prompt,
        "evaluation_type": evaluation_type,
        "period_start": period_start,
        "period_end": period_end,
        "previous_period_start": previous_period_start,
        "report": {},
        "computed_metadata": None,
    }

    try:
        result = agent.invoke(
            initial_state,
            {"recursion_limit": EVAL_REPORT_AGENT_RECURSION_LIMIT},
        )

        report = result.get("report", {})

        # Compute metadata independently — InjectedState doesn't propagate
        # key replacements back to graph state, so we query directly.
        metadata = _compute_metadata(team_id, evaluation_id, period_start, period_end, previous_period_start)

        logger.info(
            "eval_report_agent_completed",
            team_id=team_id,
            evaluation_id=evaluation_id,
            sections_written=len([s for s in report.values() if s is not None]),
            metadata=metadata.to_dict() if metadata else None,
        )

        return _fill_missing_sections(report, metadata), metadata

    except Exception as e:
        logger.exception(
            "eval_report_agent_error",
            error=str(e),
            error_type=type(e).__name__,
            team_id=team_id,
            evaluation_id=evaluation_id,
        )
        return _fill_missing_sections({}, None), None
