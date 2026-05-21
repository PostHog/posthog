"""Reusable primitive for "generate a markdown AI report from a user prompt".

This is the shared LLM pipeline that the scheduled AI-subscription delivery path
and the ad-hoc MCP / API report endpoint both run. The function takes only the
inputs the LLM needs (team, user, prompt, window) and returns the synthesized
markdown — persistence and delivery are the caller's responsibility.
"""

import re
import uuid
import asyncio
from datetime import UTC, datetime
from typing import Optional, Union

import structlog

from posthog.schema import AssistantHogQLQuery

from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.text_sanitization import strip_llm_framing_markers

from ee.hogai.context.insight.query_executor import AssistantQueryExecutor
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.tasks.subscriptions.ai_subscription.prompts import AI_SUBSCRIPTION_SYNTHESIS_PROMPT, HOGQL_FIX_PROMPT
from ee.tasks.subscriptions.ai_subscription.schemas import EnrichedPromptSpec, HogQLFix, QueryPlanStep
from ee.tasks.subscriptions.ai_subscription.spec_generator import (
    DEFAULT_PLANNER_MODEL,
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
# Backstop length cap on a single step's formatted results before they enter the synthesis
# prompt. The executor already truncates; this is defense-in-depth against a giant value.
_QUERY_RESULT_MAX_CHARS = 50_000

# Per-step query-fix budget. The planner LLM occasionally emits HogQL that fails
# to parse or resolve; rather than dropping the step's data, we feed the error
# back to the LLM and ask for a rewrite. Worst-case wall-clock per step:
#   original (60s HogQL) + 2 × (30s LLM + 60s HogQL) = ~3.5 min.
# With up to 5 steps fanned out via asyncio.gather, this stays well inside the
# Temporal activity deadline.
_MAX_QUERY_FIX_RETRIES = 2
_FIX_LLM_TIMEOUT_SECONDS = 30.0

# Errors signalling "the query itself is wrong" — rewriting may help. Everything
# else (timeouts, infra failures, generic exceptions) falls through to the
# "_Query failed_" placeholder without retrying, since a different SELECT won't
# fix a ClickHouse outage or a heartbeat timeout.
_RETRYABLE_QUERY_ERRORS: tuple[type[BaseException], ...] = (
    MaxToolRetryableError,
    ExposedHogQLError,
    InternalHogQLError,
)


class AiReportStageError(Exception):
    """Wraps a transient pipeline failure with the stage that produced it, so the
    SubscriptionDelivery error record (and the ad-hoc 500) distinguishes a planner
    timeout from a synthesis timeout instead of surfacing a bare ``TimeoutError``.

    ``PromptRejectedError`` is intentionally NOT wrapped — callers catch it directly
    to auto-disable the subscription / return a 400, so it must keep its own type.
    """

    def __init__(self, stage: str, original: BaseException) -> None:
        self.stage = stage
        self.original = original
        super().__init__(f"AI report failed at {stage} stage: {original}")


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
    propagate as :class:`AiReportStageError` (carrying ``.stage``) so the delivery
    error record names the failing stage; Temporal still retries them type-agnostically.

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

    try:
        spec = build_enriched_prompt(
            team=team,
            user=user,
            prompt=prompt,
            window_days=window_days,
            ai_config=ai_config,
            trace_correlation_id=trace_correlation_id,
        )
    except PromptRejectedError:
        raise
    except Exception as exc:
        raise AiReportStageError("planner", exc) from exc

    try:
        # Runs inside a `database_sync_to_async(thread_sensitive=False)` worker thread,
        # which has no running event loop — so `asyncio.run` is safe here.
        rendered_results, failed_count = asyncio.run(_arun_plan(spec, team, user, ai_config, trace_correlation_id))
    except Exception as exc:
        raise AiReportStageError("query", exc) from exc

    if failed_count:
        # A degraded report still ships (graceful degradation), so it is NOT a hard failure and
        # won't surface in the delivery-failure SLO. Emit a distinct, queryable signal so the
        # degraded-delivery rate can be tracked and alerted on separately from hard failures.
        logger.warning(
            "ai_report.delivered_degraded",
            trace_correlation_id=trace_correlation_id,
            failed_steps=failed_count,
            total_steps=len(spec.plan.steps),
        )

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
        # AI report LLM spend is billable — usage counts against the team's AI credits.
        billable=True,
        posthog_properties=posthog_properties,
    )

    try:
        result = chat.invoke(
            [
                ("system", AI_SUBSCRIPTION_SYNTHESIS_PROMPT),
                ("human", _compose_synthesis_human_message(spec, rendered_results)),
            ]
        )
    except Exception as exc:
        raise AiReportStageError("synthesis", exc) from exc
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
    user: User,
    ai_config: Optional[dict],
    trace_correlation_id: Optional[Union[int, str]],
) -> tuple[list[str], int]:
    # Pass `user` so executor-internal permission checks and tracing match other
    # call sites (see `ee/hogai/context/insight/query_executor.py` callers in master).
    executor = AssistantQueryExecutor(team, datetime.now(tz=UTC), user=user)

    async def run_step(step: QueryPlanStep) -> tuple[str, bool]:
        current_hogql = step.hogql
        last_exc: Optional[BaseException] = None

        # attempt 0 = original query; subsequent attempts = LLM-fixed rewrites.
        for attempt in range(_MAX_QUERY_FIX_RETRIES + 1):
            try:
                query = AssistantHogQLQuery(query=current_hogql)
                formatted, _ = await asyncio.wait_for(
                    executor.arun_and_format_query(query),
                    timeout=_HOGQL_STEP_TIMEOUT_SECONDS,
                )
                # Result VALUES are attacker-influenceable: anyone with a public project token can
                # ingest events with crafted property values. Strip LLM framing markers so a poisoned
                # value can't break out of the <query_results> envelope into instruction-shaped text.
                # The shared executor doesn't sanitize — that's the consumer's job at the LLM boundary.
                safe_formatted = strip_llm_framing_markers(formatted, _QUERY_RESULT_MAX_CHARS)
                return (f"### {step.description}\n\n{safe_formatted}", True)
            except Exception as exc:
                last_exc = exc
                if attempt >= _MAX_QUERY_FIX_RETRIES or not _is_retryable_query_error(exc):
                    break
                logger.info(
                    "ai_report.query_fix_attempt",
                    trace_correlation_id=trace_correlation_id,
                    step_description=step.description,
                    attempt=attempt + 1,
                    max_retries=_MAX_QUERY_FIX_RETRIES,
                    error_type=type(exc).__name__,
                )
                fixed = await _arequest_hogql_fix(
                    original_hogql=current_hogql,
                    error_message=str(exc),
                    step_description=step.description,
                    team=team,
                    user=user,
                    ai_config=ai_config,
                    trace_correlation_id=trace_correlation_id,
                )
                if not fixed or fixed.strip() == current_hogql.strip():
                    # LLM returned nothing useful or the same query — no point looping further.
                    break
                current_hogql = fixed

        # Exhausted retries (or non-retryable error). Fall through to the placeholder.
        logger.warning(
            "ai_report.query_failed",
            trace_correlation_id=trace_correlation_id,
            step_description=step.description,
            exc_info=last_exc,
        )
        if last_exc is not None:
            capture_exception(last_exc, {"trace_correlation_id": trace_correlation_id, "stage": "query"})
        # Pass only the type, not the message — ClickHouse errors can echo
        # team-scoped identifiers (cluster URL, table names) that shouldn't ship
        # into the synthesis prompt (and thus into the rendered report).
        type_name = type(last_exc).__name__ if last_exc is not None else "UnknownError"
        return (f"### {step.description}\n\n_Query failed: {type_name}_", False)

    step_results: list[tuple[str, bool]] = await asyncio.gather(*(run_step(step) for step in spec.plan.steps))
    rendered = [text for text, _ in step_results]
    failed_count = sum(1 for _, ok in step_results if not ok)
    return rendered, failed_count


def _is_retryable_query_error(exc: BaseException) -> bool:
    return isinstance(exc, _RETRYABLE_QUERY_ERRORS)


async def _arequest_hogql_fix(
    *,
    original_hogql: str,
    error_message: str,
    step_description: str,
    team: Team,
    user: User,
    ai_config: Optional[dict],
    trace_correlation_id: Optional[Union[int, str]],
) -> Optional[str]:
    """Ask the planner-class LLM to rewrite a failing HogQL query. Returns None on failure."""
    model_name = resolve_ai_model(ai_config, "planner_model", DEFAULT_PLANNER_MODEL)
    posthog_properties: dict[str, Union[str, int]] = {"feature": "ai_subscription", "stage": "query_fix"}
    if trace_correlation_id is not None:
        posthog_properties["subscription_id"] = trace_correlation_id

    llm = MaxChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=_FIX_LLM_TIMEOUT_SECONDS,
        user=user,
        team=team,
        # Billable, matching the planner/synthesis calls — the whole pipeline's LLM
        # usage is charged to the team's AI credits.
        billable=True,
        posthog_properties=posthog_properties,
    ).with_structured_output(HogQLFix, method="json_schema", include_raw=False)

    # Single-pass substitution — see spec_generator.generate_query_plan for the
    # rationale behind not using chained .replace().
    substitutions = {
        "description": step_description,
        "error": error_message,
        "original_hogql": original_hogql,
    }
    rendered = re.sub(
        r"\{\{\{(\w+)\}\}\}",
        lambda m: substitutions.get(m.group(1), m.group(0)),
        HOGQL_FIX_PROMPT,
    )

    try:
        result = await asyncio.to_thread(llm.invoke, [("system", rendered)])
    except Exception as exc:
        logger.warning(
            "ai_report.query_fix_llm_failed",
            trace_correlation_id=trace_correlation_id,
            step_description=step_description,
            error_type=type(exc).__name__,
        )
        return None

    if not isinstance(result, HogQLFix):
        return None
    fixed = result.fixed_hogql.strip()
    return fixed or None


__all__ = ["generate_ai_report", "AiReportStageError"]
