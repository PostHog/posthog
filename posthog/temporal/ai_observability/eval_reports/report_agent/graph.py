"""LangGraph agent for evaluation report generation using create_react_agent."""

import uuid
from typing import Any

import structlog
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent

from posthog.llm.gateway_client import team_distinct_id
from posthog.temporal.ai_observability.eval_reports.output_types import get_outcome_definition
from posthog.temporal.ai_observability.eval_reports.report_agent.prompts import build_eval_report_system_prompt
from posthog.temporal.ai_observability.eval_reports.report_agent.schema import (
    MAX_REPORT_SECTIONS,
    MIN_REPORT_SECTIONS,
    EvalReportContent,
    EvalReportGenerationStatus,
    EvalReportMetrics,
    ReportSection,
)
from posthog.temporal.ai_observability.eval_reports.report_agent.state import EvalReportAgentState
from posthog.temporal.ai_observability.eval_reports.report_agent.tools import (
    _ch_ts,
    _fetch_period_summary,
    _is_retriable_ch_error,
    get_eval_report_tools,
)
from posthog.temporal.ai_observability.eval_reports.targets import (
    GENERATION_TARGET,
    SESSION_ID_ALLOWLIST_KEY,
    TRACE_ID_ALLOWLIST_KEY,
    get_target_descriptor,
)
from posthog.temporal.ai_observability.eval_reports.types import RunEvalReportAgentInput
from posthog.temporal.ai_observability.llm_endpoint import build_langchain_callbacks, build_langchain_chat_client

logger = structlog.get_logger(__name__)


def _compute_metrics(
    team_id: int,
    evaluation_id: str,
    period_start: str,
    period_end: str,
    previous_period_start: str,
    output_type: str = "boolean",
    evaluation_target: str = GENERATION_TARGET,
) -> EvalReportMetrics | None:
    """Compute report metrics directly via HogQL (independent of agent state).

    Returns None when a transient ClickHouse failure exhausts the query helper's
    retries. Other exceptions propagate so deterministic application errors do
    not become successful fallback reports.
    """
    try:
        ts_start = _ch_ts(period_start)
        ts_end = _ch_ts(period_end)
        ts_prev_start = _ch_ts(previous_period_start)
        definition = get_outcome_definition(output_type)

        result_counts, total = _fetch_period_summary(
            team_id, evaluation_id, ts_start, ts_end, definition, evaluation_target
        )
        previous_result_counts, previous_total = _fetch_period_summary(
            team_id, evaluation_id, ts_prev_start, ts_start, definition, evaluation_target
        )

        return EvalReportMetrics(
            output_type=output_type,
            total_runs=total,
            result_counts=result_counts,
            period_start=period_start,
            period_end=period_end,
            previous_total_runs=previous_total,
            previous_result_counts=previous_result_counts,
        )
    except Exception as error:
        if not _is_retriable_ch_error(error):
            raise
        logger.exception("llma_eval_reports_metrics_computation_failed")
        return None


def _metrics_unavailable_content(
    evaluation_target: str = "generation",
) -> EvalReportContent:
    return EvalReportContent(
        evaluation_target=evaluation_target,
        title="Metrics unavailable for this period",
        sections=[],
        citations=[],
        metrics=None,
        generation_status=EvalReportGenerationStatus.METRICS_UNAVAILABLE,
    )


def _fallback_content(
    evaluation_name: str,
    metrics: EvalReportMetrics,
    reason: str,
    evaluation_target: str = "generation",
) -> EvalReportContent:
    """Produce a minimal valid EvalReportContent when the agent fails or validates out.

    The metrics are always populated (we compute them independently), so even
    the fallback report has real numbers. The single section describes what
    went wrong at the agent level so the user isn't left staring at an empty UI.
    """
    if metrics.total_runs == 0:
        unit_label = get_target_descriptor(evaluation_target).unit_label
        ingestion_hint = (
            "`$ai_generation` events are being ingested"
            if evaluation_target == GENERATION_TARGET
            else f"{unit_label} evaluation results are being ingested"
        )
        summary = (
            f"No evaluation runs recorded for **{evaluation_name}** in this period. "
            f"Check that the evaluation is enabled and that {ingestion_hint}."
        )
    elif metrics.output_type == "boolean":
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
            f"{metrics.result_counts['pass']} passed, {metrics.result_counts['fail']} failed, "
            f"{metrics.result_counts['na']} N/A."
        )
    else:
        positive_rate = metrics.result_rates["positive"]
        trend = ""
        previous_positive_rate = (
            metrics.previous_result_rates.get("positive") if metrics.previous_result_rates is not None else None
        )
        if previous_positive_rate is not None:
            diff = positive_rate - previous_positive_rate
            if diff > 1:
                trend = f"; Positive is up from {previous_positive_rate}%"
            elif diff < -1:
                trend = f"; Positive is down from {previous_positive_rate}%"
            else:
                trend = f"; Positive is stable vs {previous_positive_rate}%"

        distribution = ", ".join(
            f"{label} {metrics.result_rates[outcome]}% ({metrics.result_counts[outcome]} {outcome})"
            for outcome, label in (("positive", "Positive"), ("neutral", "Neutral"), ("negative", "Negative"))
        )
        summary = f"**Outcome distribution:** {distribution}{trend}, across {metrics.total_runs} runs."

    return EvalReportContent(
        evaluation_target=evaluation_target,
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
    refs_lines = [f"{i}. `{c.cited_id()}` — {c.reason}" for i, c in enumerate(content.citations, 1)]
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
    inputs: RunEvalReportAgentInput,
    evaluation_target: str = "generation",
) -> EvalReportContent:
    """Run the evaluation report agent and return the generated content.

    The returned EvalReportContent has `metrics` computed mechanically from
    ClickHouse (not from the agent), so downstream consumers can trust the
    numbers without parsing prose.
    """
    from posthog.temporal.ai_observability.eval_reports.constants import (
        EVAL_REPORT_AGENT_MODEL,
        EVAL_REPORT_AGENT_RECURSION_LIMIT,
        EVAL_REPORT_AGENT_TIMEOUT,
    )

    # Compute metrics first — we need them for both the final content AND the
    # fallback path, so guarantee they're ready before the agent even runs.
    metrics = _compute_metrics(
        inputs.team_id,
        inputs.evaluation_id,
        inputs.period_start,
        inputs.period_end,
        inputs.previous_period_start,
        output_type=inputs.output_type,
        evaluation_target=evaluation_target,
    )

    from posthog.temporal.ai_observability.eval_reports.metrics import increment_errors, increment_report_generated

    # The agent's query tools would fail under the same sustained ClickHouse load,
    # which could produce a narrative built on missing data.
    if metrics is None:
        increment_report_generated("fallback_metrics_unavailable")
        increment_errors("metrics_unavailable")
        logger.warning(
            "llma_eval_reports_metrics_unavailable",
            team_id=inputs.team_id,
            evaluation_id=inputs.evaluation_id,
        )
        return _metrics_unavailable_content(evaluation_target)

    resolved_trace_id = inputs.trace_id or str(uuid.uuid4())
    resolved_session_id = inputs.session_id or resolved_trace_id
    resolved_distinct_id = team_distinct_id(inputs.team_id)
    observability_properties = {
        "team_id": str(inputs.team_id),
        "evaluation_id": inputs.evaluation_id,
        **({"report_id": inputs.report_id} if inputs.report_id else {}),
    }
    llm = build_langchain_chat_client(
        EVAL_REPORT_AGENT_MODEL,
        EVAL_REPORT_AGENT_TIMEOUT,
        ai_product="aio_eval_reports",
        trace_id=resolved_trace_id,
        session_id=resolved_session_id,
        properties=observability_properties,
        distinct_id=resolved_distinct_id,
    )

    system_prompt = build_eval_report_system_prompt(
        evaluation_name=inputs.evaluation_name,
        evaluation_description=inputs.evaluation_description,
        evaluation_type=inputs.evaluation_type,
        evaluation_target=evaluation_target,
        evaluation_prompt=inputs.evaluation_prompt,
        output_type=inputs.output_type,
        period_start=inputs.period_start,
        period_end=inputs.period_end,
        report_prompt_guidance=inputs.report_prompt_guidance,
    )

    agent = create_react_agent(
        model=llm,
        tools=get_eval_report_tools(evaluation_target, inputs.output_type),
        prompt=system_prompt,
        state_schema=EvalReportAgentState,
    )

    # Seed the report with the computed metrics so they're available to the agent
    # via state if it wants to introspect, but the agent cannot mutate them —
    # we overwrite with the trusted metrics after the agent finishes anyway.
    initial_state: dict[str, Any] = {
        "messages": [HumanMessage(content="Please generate the evaluation report.")],
        "team_id": inputs.team_id,
        "evaluation_id": inputs.evaluation_id,
        "evaluation_name": inputs.evaluation_name,
        "evaluation_description": inputs.evaluation_description,
        "evaluation_prompt": inputs.evaluation_prompt,
        "evaluation_type": inputs.evaluation_type,
        "evaluation_target": evaluation_target,
        "output_type": inputs.output_type,
        "period_start": inputs.period_start,
        "period_end": inputs.period_end,
        "previous_period_start": inputs.previous_period_start,
        "report_prompt_guidance": inputs.report_prompt_guidance,
        "report": EvalReportContent(evaluation_target=evaluation_target, metrics=metrics),
        TRACE_ID_ALLOWLIST_KEY: [],
        SESSION_ID_ALLOWLIST_KEY: [],
    }

    callbacks = build_langchain_callbacks(
        distinct_id=resolved_distinct_id,
        trace_id=resolved_trace_id,
        session_id=resolved_session_id,
        ai_product="aio_eval_reports",
        properties=observability_properties,
    )

    config: RunnableConfig = {
        "recursion_limit": EVAL_REPORT_AGENT_RECURSION_LIMIT,
        "callbacks": callbacks,
    }

    try:
        result = agent.invoke(initial_state, config)

        content: EvalReportContent = result.get(
            "report", EvalReportContent(evaluation_target=evaluation_target, metrics=metrics)
        )
        # Always overwrite metrics with the trusted computation — the agent cannot
        # fabricate numbers by mutating state["report"].metrics.
        content.evaluation_target = evaluation_target
        content.metrics = metrics

        validation_error = _validate_agent_output(content)
        if validation_error:
            increment_report_generated("fallback_validation")

            logger.warning(
                "llma_eval_reports_agent_validation_failed",
                team_id=inputs.team_id,
                evaluation_id=inputs.evaluation_id,
                reason=validation_error,
                title=content.title,
                section_count=len(content.sections),
                trace_id=resolved_trace_id,
                session_id=resolved_session_id,
            )
            return _fallback_content(inputs.evaluation_name, metrics, validation_error, evaluation_target)

        _append_references_section(content)

        increment_report_generated("completed")

        logger.info(
            "llma_eval_reports_agent_completed",
            team_id=inputs.team_id,
            evaluation_id=inputs.evaluation_id,
            title=content.title,
            section_count=len(content.sections),
            citation_count=len(content.citations),
            metrics=metrics.to_dict(),
            trace_id=resolved_trace_id,
            session_id=resolved_session_id,
        )
        return content

    except Exception as e:
        increment_report_generated("fallback_error")
        increment_errors(f"agent_{type(e).__name__}")

        logger.exception(
            "llma_eval_reports_agent_error",
            error=str(e),
            error_type=type(e).__name__,
            team_id=inputs.team_id,
            evaluation_id=inputs.evaluation_id,
            trace_id=resolved_trace_id,
            session_id=resolved_session_id,
        )
        return _fallback_content(
            inputs.evaluation_name,
            metrics,
            f"agent raised {type(e).__name__}",
            evaluation_target,
        )
