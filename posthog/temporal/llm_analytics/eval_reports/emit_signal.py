"""Emit a signal per evaluation report run.

Parallel to `products/signals/backend/temporal/emit_eval_signal.py` which emits
one signal per individual `$ai_evaluation` result. This module emits one signal
per report run, which is strictly more useful because a report already aggregates
the underlying results into an analytical narrative (trend, patterns, citations)
— the signal inherits that narrative rather than the per-result verdict.

The same `SignalSourceConfig(LLM_ANALYTICS, EVALUATION)` toggle gates both:
enabling signals for an evaluation lights up per-result AND per-report-run
emission. No new config surface.

Lives in `posthog/temporal/llm_analytics/` (not `products/signals/`) because
this is fundamentally an LLMA operation: it runs on the LLMA worker, reads the
LLMA `EvaluationReportRun` model, and only the terminal `emit_signal` call
crosses into Signals. Keeping it here also satisfies tach's rule that
`products.signals` cannot depend on `products.llm_analytics`.
"""

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
import temporalio
import temporalio.activity
import temporalio.workflow
from pydantic import BaseModel, Field
from temporalio.common import RetryPolicy

from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow

from products.llm_analytics.backend.models.evaluation_reports import EvaluationReportRun
from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.temporal.llm import call_llm

logger = structlog.get_logger(__name__)


@dataclass
class EmitEvalReportSignalInputs:
    """Strongly typed inputs for the eval report signal workflow and activity.

    Intentionally lightweight — `content` is fetched from `EvaluationReportRun` inside
    the activity rather than passed through the workflow → child → activity chain so
    we stay well under Temporal's ~2 MiB per-payload limit (a dense report with many
    citations/sections can easily push past the 256 KiB conservative threshold).
    """

    team_id: int
    evaluation_id: str
    evaluation_name: str
    evaluation_description: str
    evaluation_prompt: str

    report_id: str
    report_run_id: str
    period_start: str
    period_end: str


class EvalReportSignalSummary(BaseModel):
    title: str = Field(description="Short title describing what this report surfaced (max 100 chars)", max_length=100)
    description: str = Field(description="4-8 sentence description of the report's finding and why it matters")
    significance: float = Field(ge=0.0, le=1.0)


SUMMARIZE_REPORT_SYSTEM_PROMPT = """You are a concise technical writer. Your job is to produce a short signal description from a PostHog LLM evaluation REPORT.

Unlike a per-result signal (one judge verdict), a report is an analytical narrative over many evaluation results in a time window. It already contains a title, several titled sections, metrics, and citations to specific generations. Your output should distill that narrative into a signal that fits alongside signals from other observability tools.

You will be given:
- Evaluation context: name, optional description, and the judge criteria prompt
- Report period (start/end timestamps)
- Report content: the agent-chosen title, sections (each with a title and markdown body), citations, and structured metrics (total_runs, pass_count, fail_count, na_count, pass_rate, previous_pass_rate)

Produce:
1. A short title (max 100 chars) capturing the report's main finding as a statement, not a question.
   Good: "Pass rate dropped 14pp on the cost-cap eval"
   Good: "Tool-call loops concentrated in the weekend refresh batch"
   Bad: "Evaluation report for cost-cap-v2"
   Bad: "Pass rate was 72%"

2. A 4-8 sentence description that explains:
   - Open with what the evaluation is measuring (derived from the evaluation name, description, and judge criteria prompt). Name the evaluation explicitly — the reader may have no prior context. One sentence is enough.
   - What changed or is notable about the evaluation's behavior over the period
   - Concrete metrics that support the finding (pass_rate, delta vs previous period if available, total_runs)
   - Any pattern the report identifies (e.g. specific failure mode, particular model, time-of-day clustering)
   - If citations are present, reference that traces are available for investigation

3. A significance score between 0 and 1:
   - 0.0-0.1 = noise / expected behavior / nothing changed meaningfully
   - 0.2-0.4 = minor finding, worth noting but low priority
   - 0.5-0.7 = moderate, should be investigated when time permits
   - 0.8-0.9 = high, should be prioritized
   - 1.0 = critical, act immediately

Base significance on: magnitude of pass_rate change, absolute failure rate, breadth across generations (citation count as proxy), and how actionable the finding is from the report's prose.

The output will be fed into a signal grouping and investigation system that groups related findings across observability tools. Write for an engineer who hasn't seen this evaluation before.

Do NOT parrot the report's title verbatim. Do NOT say "the report shows" — state the finding directly.

Keep total output under 4000 tokens — be concise.

Respond with a JSON object containing "title", "description", and "significance" fields. Return ONLY valid JSON, no other text. The first token of output must be {"""


def _build_eval_report_signal_prompt(inputs: EmitEvalReportSignalInputs, content: dict[str, Any]) -> str:
    """Serialize the inputs into a compact prompt for the summarizer.

    Passes the full report content as JSON so the LLM has access to titles,
    sections, metrics, and citations in their original structure.
    """
    parts = [
        f"EVALUATION NAME: {inputs.evaluation_name}",
    ]
    if inputs.evaluation_description:
        parts.append(f"\nEVALUATION DESCRIPTION: {inputs.evaluation_description}")
    if inputs.evaluation_prompt:
        parts.append(f"\nEVALUATION PROMPT (judge criteria):\n{inputs.evaluation_prompt}")
    parts.append(f"\nREPORT PERIOD: {inputs.period_start} → {inputs.period_end}")
    parts.append(f"\nREPORT CONTENT (JSON):\n{json.dumps(content, default=str)}")
    return "\n".join(parts)


async def summarize_report_for_signal(
    inputs: EmitEvalReportSignalInputs, content: dict[str, Any]
) -> EvalReportSignalSummary:
    """Use the signals LLM to produce a signal-sized summary of a report run."""
    user_prompt = _build_eval_report_signal_prompt(inputs, content)

    def validate(text: str) -> EvalReportSignalSummary:
        data = json.loads(text)
        return EvalReportSignalSummary.model_validate(data)

    return await call_llm(
        system_prompt=SUMMARIZE_REPORT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        validate=validate,
        thinking=True,
    )


@temporalio.activity.defn
async def emit_eval_report_signal_activity(inputs: EmitEvalReportSignalInputs) -> None:
    """Summarize a report run and emit a signal if the evaluation is allowlisted.

    Gated by the same SignalSourceConfig(LLM_ANALYTICS, EVALUATION) row that
    governs per-result signal emission. No separate toggle — enabling signals
    for an evaluation turns on both per-result and per-report emission.

    No significance threshold — we emit every run that passes the config gate.
    The downstream signal grouping system already handles deduplication and
    relevance filtering, so letting low-significance runs through as noise
    is cheaper than trying to guess a threshold that holds across all evals.
    """

    def _is_eval_enabled() -> Team | None:
        try:
            source_config = SignalSourceConfig.objects.get(
                team_id=inputs.team_id,
                source_product=SignalSourceConfig.SourceProduct.LLM_ANALYTICS,
                source_type=SignalSourceConfig.SourceType.EVALUATION,
                enabled=True,
            )
        except SignalSourceConfig.DoesNotExist:
            return None

        enabled_ids = source_config.config.get("evaluation_ids", [])
        if inputs.evaluation_id not in enabled_ids:
            return None

        return Team.objects.get(id=inputs.team_id)

    team = await database_sync_to_async(_is_eval_enabled, thread_sensitive=False)()
    if team is None:
        return

    organization = await database_sync_to_async(lambda: team.organization)()
    if not organization.is_ai_data_processing_approved:
        return

    def _fetch_report_content() -> dict[str, Any]:
        return EvaluationReportRun.objects.values_list("content", flat=True).get(id=inputs.report_run_id)

    content = await database_sync_to_async(_fetch_report_content, thread_sensitive=False)()

    summary = await summarize_report_for_signal(inputs, content)

    from products.signals.backend.api import emit_signal

    await emit_signal(
        team=team,
        source_product="llm_analytics",
        source_type="evaluation_report",
        source_id=f"{inputs.evaluation_id}:report:{inputs.report_run_id}",
        description=summary.description,
        weight=summary.significance,
        extra={
            "evaluation_id": inputs.evaluation_id,
            "evaluation_name": inputs.evaluation_name,
            "evaluation_description": inputs.evaluation_description,
            "report_id": inputs.report_id,
            "report_run_id": inputs.report_run_id,
            "period_start": inputs.period_start,
            "period_end": inputs.period_end,
        },
    )

    logger.info(
        "Emitted eval report signal",
        evaluation_id=inputs.evaluation_id,
        report_run_id=inputs.report_run_id,
        team_id=inputs.team_id,
        signal_title=summary.title,
    )


@temporalio.workflow.defn(name="emit-eval-report-signal")
class EmitEvalReportSignalWorkflow(PostHogWorkflow):
    """Dedicated workflow for emitting eval report signals.

    Runs on LLMA_TASK_QUEUE alongside the parent GenerateAndDeliverEvalReportWorkflow.
    Fire-and-forget — the caller uses ParentClosePolicy.ABANDON so the report
    workflow doesn't wait for signal emission (which does its own LLM call) to
    complete, even though both run on the same worker.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> EmitEvalReportSignalInputs:
        loaded = json.loads(inputs[0])
        return EmitEvalReportSignalInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: EmitEvalReportSignalInputs) -> None:
        await temporalio.workflow.execute_activity(
            emit_eval_report_signal_activity,
            inputs,
            schedule_to_close_timeout=timedelta(seconds=180),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
