"""Reusable primitive for "generate a markdown AI report from a user prompt".

This is the shared LLM pipeline that the scheduled AI-subscription delivery path
and the ad-hoc MCP / API report endpoint both run. The function takes only the
inputs the LLM needs (team, user, prompt, window) and returns the synthesized
markdown — persistence and delivery are the caller's responsibility.
"""

import uuid
import asyncio
from datetime import UTC, datetime
from typing import Optional, Union

import structlog

from posthog.schema import AssistantHogQLQuery

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from ee.hogai.context.insight.query_executor import AssistantQueryExecutor
from ee.hogai.llm import MaxChatOpenAI
from ee.tasks.subscriptions.ai_subscription.prompts import AI_SUBSCRIPTION_SYNTHESIS_PROMPT
from ee.tasks.subscriptions.ai_subscription.schemas import EnrichedPromptSpec
from ee.tasks.subscriptions.ai_subscription.spec_generator import (
    DEFAULT_SYNTHESIS_MODEL,
    PromptRejectedError,
    build_enriched_prompt,
    resolve_ai_model,
)

logger = structlog.get_logger(__name__)

# Wall-clock bounds for the in-band LLM + HogQL pipeline. The caller's outer
# deadline (Temporal activity timeout for scheduled, request timeout for ad-hoc)
# is the ultimate cap; these prevent a single slow upstream from soaking it.
_SYNTHESIS_LLM_TIMEOUT_SECONDS = 90.0
_HOGQL_STEP_TIMEOUT_SECONDS = 60.0


def generate_ai_report(
    *,
    team: Team,
    user: User,
    prompt: Optional[str],
    window_days: int,
    ai_config: Optional[dict] = None,
    trace_correlation_id: Optional[Union[int, str]] = None,
) -> str:
    """Run the planner → HogQL → synthesis pipeline and return the markdown report.

    Raises :class:`PromptRejectedError` for permanent input failures (missing user,
    empty/oversize prompt, malformed planner output). Transient LLM / HogQL failures
    propagate as their original exceptions so the caller can decide whether to retry.

    :param team: The team whose data the report describes. Drives HogQL execution.
    :param user: The user the LLM call is billed to. Must be non-None.
    :param prompt: The user's natural-language request. Sanitized inside.
    :param window_days: Analysis window the planner should consider (e.g. 7 for weekly).
    :param ai_config: Optional dict with overrides — currently ``model`` and ``planner_model``.
        Values outside :data:`ALLOWED_AI_MODELS` are silently ignored at delivery time.
    :param trace_correlation_id: Optional id forwarded to LLM call analytics so the
        scheduled-vs-ad-hoc origin and the upstream subscription/request can be traced.
    """
    if user is None:
        raise PromptRejectedError("AI report must have a user to run.")

    spec = build_enriched_prompt(
        team=team,
        user=user,
        prompt=prompt,
        window_days=window_days,
        ai_config=ai_config,
        trace_correlation_id=trace_correlation_id,
    )
    rendered_results = asyncio.run(_arun_plan(spec, team, trace_correlation_id))

    model_name = resolve_ai_model(ai_config, "model", DEFAULT_SYNTHESIS_MODEL)
    posthog_properties: dict[str, Union[str, int]] = {
        "feature": "ai_subscription",
        "stage": "synthesis",
        "trace_id": str(uuid.uuid4()),
    }
    if trace_correlation_id is not None:
        posthog_properties["subscription_id"] = trace_correlation_id

    chat = MaxChatOpenAI(
        model=model_name,
        temperature=0.2,
        timeout=_SYNTHESIS_LLM_TIMEOUT_SECONDS,
        user=user,
        team=team,
        # `billable=False` while AI reports are in beta — PostHog absorbs the LLM
        # spend. Flip to True when usage-based billing is wired.
        billable=False,
        posthog_properties=posthog_properties,
    )

    result = chat.invoke(
        [
            ("system", AI_SUBSCRIPTION_SYNTHESIS_PROMPT),
            ("human", _compose_synthesis_human_message(spec, rendered_results)),
        ]
    )
    content = result.content if hasattr(result, "content") else str(result)
    return content if isinstance(content, str) else str(content)


def _compose_synthesis_human_message(spec: EnrichedPromptSpec, rendered_results: list[str]) -> str:
    results_block = "\n".join(rendered_results) if rendered_results else "_No query results were available._"
    return (
        f"<user_prompt>\n{spec.cleaned_prompt}\n</user_prompt>\n\n"
        f"<project_context>\n{spec.context_blob}\n</project_context>\n\n"
        f"Plan intent (system-provided, not user-controlled): {spec.plan.overall_intent}\n\n"
        f"<query_results>\n{results_block}\n</query_results>"
    )


async def _arun_plan(
    spec: EnrichedPromptSpec,
    team: Team,
    trace_correlation_id: Optional[Union[int, str]],
) -> list[str]:
    executor = AssistantQueryExecutor(team, datetime.now(tz=UTC))

    async def run_step(step) -> str:
        try:
            query = AssistantHogQLQuery(query=step.hogql)
            formatted, _ = await asyncio.wait_for(
                executor.arun_and_format_query(query),
                timeout=_HOGQL_STEP_TIMEOUT_SECONDS,
            )
            return f"### {step.description}\n\n{formatted}"
        except Exception as exc:
            logger.warning(
                "ai_report.query_failed",
                trace_correlation_id=trace_correlation_id,
                step_description=step.description,
                exc_info=True,
            )
            capture_exception(exc, {"trace_correlation_id": trace_correlation_id, "stage": "query"})
            # Pass only the type, not the message — ClickHouse errors can echo
            # team-scoped identifiers (cluster URL, table names) that shouldn't ship
            # into the synthesis prompt (and thus into the rendered report).
            return f"### {step.description}\n\n_Query failed: {type(exc).__name__}_"

    return await asyncio.gather(*(run_step(step) for step in spec.plan.steps))


__all__ = ["generate_ai_report"]
