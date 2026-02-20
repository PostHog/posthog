import json
from dataclasses import dataclass
from typing import Any

import structlog
import temporalio
from pydantic import BaseModel, Field

from posthog.models.team import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.api import emit_signal
from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.temporal.llm import call_llm

logger = structlog.get_logger(__name__)


class EvalSignalSummary(BaseModel):
    title: str = Field(
        description="Short title describing what this evaluation detected (max 100 chars)", max_length=100
    )
    description: str = Field(description="4-8 sentence description of the evaluation goal and why it passed")
    significance: float = Field(ge=0.0, le=1.0)


SUMMARIZE_EVAL_SYSTEM_PROMPT = """You are a concise technical writer. Your job is to produce a short signal description from an LLM trace evaluation result.

You will be given:
- The evaluation name
- The full evaluation prompt (the criteria the judge used)
- The judge's reasoning for its verdict
- Context about the target event (event type, trace ID if available)

Produce:
1. A short title (max 100 chars) that captures what the evaluation detected. This should read as a finding, not a question.
   Good: "Hallucination detected in product recommendation flow"
   Bad: "Evaluation 'hallucination_check' passed"

2. A 4-8 sentence description that explains:
   - What the evaluation was checking for (derived from the prompt)
   - Why the judge determined the result was true
   - Any relevant context about the trace or event

3. A significance score between 0 and 1:
   - 0.0 = totally insignificant, noise, expected behavior
   - 0.1-0.3 = minor, worth noting but low priority
   - 0.4-0.6 = moderate, should be investigated when time permits
   - 0.7-0.9 = high, should be prioritized and addressed soon
   - 1.0 = critical, should be acted on immediately

Base significance on: severity of the finding, breadth of impact, and how obvious or actionable the fix is.

The output will be fed into a signal grouping and investigation system that groups related findings from different observability tools and data sources, across an entire product.
Write for an engineer who hasn't seen this specific evaluation before.
Do NOT parrot the evaluation name or say "the evaluation passed". Describe the actual finding.

Keep total output under 4000 tokens - be as concise as possible, without losing important information for the downstream investigators.

Respond with a JSON object containing "title", "description", and "significance" fields. Return ONLY valid JSON, no other text. The first token of output must be {"""


def _build_eval_signal_prompt(
    evaluation: dict[str, Any],
    event_data: dict[str, Any],
    result: dict[str, Any],
) -> str:
    eval_name = evaluation.get("name", "Unknown evaluation")
    eval_prompt = (evaluation.get("evaluation_config") or {}).get("prompt", "")
    reasoning = result.get("reasoning", "")

    properties = event_data.get("properties", {})
    if isinstance(properties, str):
        properties = json.loads(properties)
    trace_id = properties.get("$ai_trace_id", "")
    event_type = event_data.get("event", "")

    parts = [
        f"EVALUATION NAME: {eval_name}",
        f"\nEVALUATION PROMPT (judge criteria):\n{eval_prompt}",
        f"\nJUDGE REASONING:\n{reasoning}",
        f"\nTARGET EVENT TYPE: {event_type}",
    ]
    if trace_id:
        parts.append(f"TRACE ID: {trace_id}")

    return "\n".join(parts)


async def summarize_eval_for_signal(
    evaluation: dict[str, Any],
    event_data: dict[str, Any],
    result: dict[str, Any],
) -> EvalSignalSummary:
    """Use the signals LLM to produce a signal-sized summary of an eval result."""
    user_prompt = _build_eval_signal_prompt(evaluation, event_data, result)

    def validate(text: str) -> EvalSignalSummary:
        data = json.loads(text)
        return EvalSignalSummary.model_validate(data)

    return await call_llm(
        system_prompt=SUMMARIZE_EVAL_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        validate=validate,
        thinking=True,
    )


@dataclass
class EmitEvalSignalInput:
    team_id: int
    evaluation: dict[str, Any]
    event_data: dict[str, Any]
    result: dict[str, Any]


@temporalio.activity.defn
async def emit_eval_signal_activity(
    team_id: int,
    evaluation: dict[str, Any],
    event_data: dict[str, Any],
    result: dict[str, Any],
) -> None:
    verdict = result.get("verdict")
    allows_na = result.get("allows_na", False)

    if allows_na and not result.get("applicable", False):
        return
    if verdict is not True:
        return
    if not result.get("reasoning"):
        return

    evaluation_id = evaluation.get("id", "")

    def _is_eval_enabled() -> Team | None:
        """Check SignalSourceConfig and return Team if this eval is enabled, else None."""
        try:
            source_config = SignalSourceConfig.objects.get(
                team_id=team_id,
                source_type=SignalSourceConfig.SourceType.LLM_EVAL,
                enabled=True,
            )
        except SignalSourceConfig.DoesNotExist:
            return None

        enabled_ids = source_config.config.get("evaluation_ids", [])
        if evaluation_id not in enabled_ids:
            return None

        return Team.objects.get(id=team_id)

    team = await database_sync_to_async(_is_eval_enabled, thread_sensitive=False)()
    if team is None:
        return

    organization = await database_sync_to_async(lambda: team.organization)()
    if not organization.is_ai_data_processing_approved:
        return

    # LLM call to produce a signal-quality summary from the raw eval data
    summary = await summarize_eval_for_signal(evaluation, event_data, result)

    properties = event_data.get("properties", {})
    if isinstance(properties, str):
        properties = json.loads(properties)
    trace_id = properties.get("$ai_trace_id", "")

    if summary.significance < 0.1:
        return  # We just skip really low relevance signals.

    await emit_signal(
        team=team,
        source_product="llm_analytics",
        source_type="evaluation_passed",
        source_id=f"{evaluation['id']}:{event_data.get('uuid', '')}",
        description=summary.description,
        weight=summary.significance,
        extra={
            "evaluation_id": evaluation["id"],
            "target_event_id": event_data.get("uuid"),
            "target_event_type": event_data.get("event"),
            "trace_id": trace_id,
            "model": result.get("model"),
            "provider": result.get("provider"),
        },
    )

    logger.info(
        "Emitted eval signal",
        evaluation_id=evaluation.get("id"),
        team_id=team_id,
        signal_title=summary.title,
    )
