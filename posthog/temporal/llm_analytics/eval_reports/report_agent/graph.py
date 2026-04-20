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
    MAX_REPORT_SECTIONS,
    MIN_REPORT_SECTIONS,
    EvalReportContent,
    EvalReportMetrics,
    ReportSection,
)
from posthog.temporal.llm_analytics.eval_reports.report_agent.state import EvalReportAgentState
from posthog.temporal.llm_analytics.eval_reports.report_agent.tools import (
    EVAL_REPORT_TOOLS,
    _ch_ts,
    _fetch_period_counts,
)

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


def _compute_metrics(
    team_id: int,
    evaluation_id: str,
    period_start: str,
    period_end: str,
    previous_period_start: str,
) -> EvalReportMetrics:
    """Compute report metrics directly via HogQL (independent of agent state).

    Always returns a valid EvalReportMetrics — on query failure, returns one
    with zero counts and logs the exception. The agent cannot fabricate numbers
    because this function is the sole source of truth for `content.metrics`.
    """
    empty = EvalReportMetrics(period_start=period_start, period_end=period_end)

    try:
        ts_start = _ch_ts(period_start)
        ts_end = _ch_ts(period_end)
        ts_prev_start = _ch_ts(previous_period_start)

        pass_count, fail_count, na_count, total = _fetch_period_counts(team_id, evaluation_id, ts_start, ts_end)
        prev_pass, prev_fail, _prev_na, prev_total = _fetch_period_counts(
            team_id, evaluation_id, ts_prev_start, ts_start
        )

        applicable = pass_count + fail_count
        pass_rate = round(pass_count / applicable * 100, 2) if applicable > 0 else 0.0
        prev_applicable = prev_pass + prev_fail
        previous_pass_rate = round(prev_pass / prev_applicable * 100, 2) if prev_applicable > 0 else None

        return EvalReportMetrics(
            total_runs=total,
            pass_count=pass_count,
            fail_count=fail_count,
            na_count=na_count,
            pass_rate=pass_rate,
            period_start=period_start,
            period_end=period_end,
            previous_total_runs=prev_total,
            previous_pass_rate=previous_pass_rate,
        )
    except Exception:
        logger.exception("Failed to compute report metrics")
        return empty


def _fallback_content(evaluation_name: str, metrics: EvalReportMetrics, reason: str) -> EvalReportContent:
    """Produce a minimal valid EvalReportContent when the agent fails or validates out.

    The metrics are always populated (we compute them independently), so even
    the fallback report has real numbers. The single section describes what
    went wrong at the agent level so the user isn't left staring at an empty UI.
    """
    if metrics.total_runs == 0:
        summary = (
            f"No evaluation runs recorded for **{evaluation_name}** in this period. "
            f"Check that the evaluation is enabled and that `$ai_generation` events "
            f"are being ingested."
        )
    else:
        trend = ""
        if metrics.previous_pass_rate is not None:
            diff = metrics.pass_rate - metrics.previous_pass_rate
            if diff > 1:
                trend = f" (up from {metrics.previous_pass_rate}%)"
            elif diff < -1:
                trend = f" (down from {metrics.previous_pass_rate}%)"
            else:
                trend = f" (stable vs {metrics.previous_pass_rate}%)"

        summary = (
            f"**Pass rate: {metrics.pass_rate}%**{trend} across {metrics.total_runs} runs. "
            f"{metrics.pass_count} passed, {metrics.fail_count} failed, {metrics.na_count} N/A."
        )

    return EvalReportContent(
        title=f"Automated fallback report for {evaluation_name}",
        sections=[
            ReportSection(
                title="Summary",
                content=f"{summary}\n\n_Note: this is a minimal fallback report. Reason: {reason}._",
            )
        ],
        citations=[],
        metrics=metrics,
    )


def _append_references_section(content: EvalReportContent) -> None:
    """Auto-append a References section from structured citations.

    Every delivery surface (UI, email, Slack) gets a clickable bibliography.
    MAX_REPORT_SECTIONS caps the number of AGENT-authored sections; References
    is generated post-validation and sits on top as the +1 so citations never
    displace substantive content even when the agent uses the full budget.
    """
    if not content.citations:
        return
    refs_lines = [f"{i}. `{c.generation_id}` — {c.reason}" for i, c in enumerate(content.citations, 1)]
    content.sections.append(ReportSection(title="References", content="\n".join(refs_lines)))


def _validate_agent_output(content: EvalReportContent) -> str | None:
    """Return a reason string if content is invalid, else None.

    Enforced invariants:
      - title must be non-empty
      - section count must be within [MIN_REPORT_SECTIONS, MAX_REPORT_SECTIONS]
      - every section must have a non-empty title and content
    """
    if not content.title.strip():
        return "agent did not call set_title"
    if len(content.sections) < MIN_REPORT_SECTIONS:
        return f"agent produced {len(content.sections)} sections (minimum {MIN_REPORT_SECTIONS})"
    if len(content.sections) > MAX_REPORT_SECTIONS:
        return f"agent produced {len(content.sections)} sections (maximum {MAX_REPORT_SECTIONS})"
    for idx, section in enumerate(content.sections):
        if not section.title.strip():
            return f"section {idx + 1} has empty title"
        if not section.content.strip():
            return f"section {idx + 1} ({section.title!r}) has empty content"
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
    report_prompt_guidance: str = "",
) -> EvalReportContent:
    """Run the evaluation report agent and return the generated content.

    The returned EvalReportContent has `metrics` computed mechanically from
    ClickHouse (not from the agent), so downstream consumers can trust the
    numbers without parsing prose.
    """
    from posthog.temporal.llm_analytics.eval_reports.constants import (
        EVAL_REPORT_AGENT_MODEL,
        EVAL_REPORT_AGENT_RECURSION_LIMIT,
        EVAL_REPORT_AGENT_TIMEOUT,
    )

    # Compute metrics first — we need them for both the final content AND the
    # fallback path, so guarantee they're ready before the agent even runs.
    metrics = _compute_metrics(team_id, evaluation_id, period_start, period_end, previous_period_start)

    llm = _get_llm(EVAL_REPORT_AGENT_MODEL, EVAL_REPORT_AGENT_TIMEOUT)

    description_section = f"Description: {evaluation_description}\n" if evaluation_description else ""
    prompt_section = f"Evaluation prompt/criteria:\n```\n{evaluation_prompt}\n```\n" if evaluation_prompt else ""
    guidance_section = ""
    if report_prompt_guidance and report_prompt_guidance.strip():
        guidance_section = (
            "\n## Additional guidance from the user (per-report)\n\n"
            "The user provided the following custom guidance for this specific report. "
            "Treat it as a steer on focus / scope / section choices, not as a replacement "
            "for the core instructions above.\n\n"
            f"```\n{report_prompt_guidance.strip()}\n```\n"
        )

    system_prompt = EVAL_REPORT_SYSTEM_PROMPT.format(
        evaluation_name=evaluation_name,
        evaluation_description_section=description_section,
        evaluation_type=evaluation_type,
        evaluation_prompt_section=prompt_section,
        period_start=period_start,
        period_end=period_end,
        report_prompt_guidance_section=guidance_section,
        max_sections=MAX_REPORT_SECTIONS,
    )

    agent = create_react_agent(
        model=llm,
        tools=EVAL_REPORT_TOOLS,
        prompt=system_prompt,
        state_schema=EvalReportAgentState,
    )

    # Seed the report with the computed metrics so they're available to the agent
    # via state if it wants to introspect, but the agent cannot mutate them —
    # we overwrite with the trusted metrics after the agent finishes anyway.
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
        "report_prompt_guidance": report_prompt_guidance,
        "report": EvalReportContent(metrics=metrics),
    }

    try:
        result = agent.invoke(
            initial_state,
            {"recursion_limit": EVAL_REPORT_AGENT_RECURSION_LIMIT},
        )

        content: EvalReportContent = result.get("report", EvalReportContent(metrics=metrics))
        # Always overwrite metrics with the trusted computation — the agent cannot
        # fabricate numbers by mutating state["report"].metrics.
        content.metrics = metrics

        validation_error = _validate_agent_output(content)
        if validation_error:
            logger.warning(
                "eval_report_agent_validation_failed",
                team_id=team_id,
                evaluation_id=evaluation_id,
                reason=validation_error,
                title=content.title,
                section_count=len(content.sections),
            )
            return _fallback_content(evaluation_name, metrics, validation_error)

        _append_references_section(content)

        logger.info(
            "eval_report_agent_completed",
            team_id=team_id,
            evaluation_id=evaluation_id,
            title=content.title,
            section_count=len(content.sections),
            citation_count=len(content.citations),
            metrics=metrics.to_dict(),
        )
        return content

    except Exception as e:
        logger.exception(
            "eval_report_agent_error",
            error=str(e),
            error_type=type(e).__name__,
            team_id=team_id,
            evaluation_id=evaluation_id,
        )
        return _fallback_content(evaluation_name, metrics, f"agent raised {type(e).__name__}")
