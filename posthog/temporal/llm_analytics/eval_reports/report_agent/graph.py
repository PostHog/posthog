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

        logger.info(
            "eval_report_agent_completed",
            team_id=team_id,
            evaluation_id=evaluation_id,
            sections_written=len([s for s in result.get("report", {}).values() if s is not None]),
        )

        report = result.get("report", {})
        metadata = result.get("computed_metadata")
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
