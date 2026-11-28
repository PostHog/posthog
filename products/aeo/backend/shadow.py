"""Run the model that is not live next to the one that is, and record both as LLM analytics events.

The live path decides what the person sees. When shadow mode is on, a task runs the other models on the same
brands after the request has returned, and each model's decisions become one `$ai_generation` event in the
team's own project, under a trace id the read also stores. A person's later verdict on a suggested brand is
captured against that trace, so LLM analytics can compare each model's calls with what people decided.
"""

from __future__ import annotations

import time
import uuid
import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from django.conf import settings
from django.core.cache import caches

import structlog

from posthog.api.capture import CaptureInternalError, capture_internal
from posthog.dataclasses import frozen
from posthog.llm.gateway_client import team_distinct_id
from posthog.temporal.ai_observability.team_capture import capture_ai_internal_for_team, get_team_api_token

from products.aeo.backend import competitors, decisions
from products.aeo.backend.suggestions import SUGGESTION_CACHE_ALIAS

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "aeo_shadow"
SPAN_NAME = "aeo competitor confirmation"
BRAND_REVIEWED_EVENT = "aeo brand reviewed"
LIVE_HEURISTIC = "heuristic"
LIVE_JEV = "jev"
# One shadow run per team per hour: the suggestions page reloads often and the answer barely moves.
SHADOW_DEBOUNCE_SECONDS = 60 * 60
TRACE_TTL_SECONDS = 30 * 24 * 60 * 60


@frozen
class ShadowRun:
    """What one read of the competitor suggestions asked, and what the live path answered."""

    team_id: int
    trace_id: str
    site: Mapping[str, str]
    brands: tuple[competitors.BrandInput, ...]
    live_model: str
    # Domain to the live path's yes/no, so the shadow events carry the same shape as the live one.
    live_decisions: Mapping[str, bool]


@frozen
class ModelDecisions:
    model: str
    provider: str
    decisions: Mapping[str, bool]
    probabilities: Mapping[str, float]
    latency_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    error: str | None = None


def _trace_key(team_id: int) -> str:
    return f"aeo_shadow_trace:{team_id}"


def _debounce_key(team_id: int) -> str:
    return f"aeo_shadow_queued:{team_id}"


def latest_trace_id(team_id: int) -> str | None:
    value = caches[SUGGESTION_CACHE_ALIAS].get(_trace_key(team_id))
    return value if isinstance(value, str) else None


def queue_competitor_shadow(
    team_id: int,
    *,
    site: Mapping[str, str],
    brands: Sequence[competitors.BrandInput],
    live_model: str,
    live_decisions: Mapping[str, bool],
) -> str | None:
    """Start a shadow run for this read, unless one ran for the team within the debounce window. Returns the
    trace id of the run that was queued, or None. Never raises: the read must not fail because of it."""
    from products.aeo.backend.tasks.tasks import shadow_aeo_competitors_task  # noqa: PLC0415 -- import cycle

    if not brands:
        return None
    cache = caches[SUGGESTION_CACHE_ALIAS]
    if not cache.add(_debounce_key(team_id), 1, timeout=SHADOW_DEBOUNCE_SECONDS):
        return None
    trace_id = str(uuid.uuid4())
    cache.set(_trace_key(team_id), trace_id, timeout=TRACE_TTL_SECONDS)
    try:
        shadow_aeo_competitors_task.delay(
            team_id,
            {
                "trace_id": trace_id,
                "site": dict(site),
                "brands": [{"name": b.name, "domain": b.domain} for b in brands],
                "live_model": live_model,
                "live_decisions": dict(live_decisions),
            },
        )
    except Exception:
        logger.warning("aeo_shadow_enqueue_failed", team_id=team_id, exc_info=True)
        cache.delete(_debounce_key(team_id))
        return None
    return trace_id


def run_from_payload(team_id: int, payload: dict[str, Any]) -> None:
    run = ShadowRun(
        team_id=team_id,
        trace_id=str(payload["trace_id"]),
        site={str(k): str(v) for k, v in payload["site"].items()},
        brands=tuple(competitors.BrandInput(name=b["name"], domain=b["domain"]) for b in payload["brands"]),
        live_model=str(payload["live_model"]),
        live_decisions={str(k): bool(v) for k, v in payload["live_decisions"].items()},
    )
    run_shadow(run)


def jev_decisions(run: ShadowRun) -> ModelDecisions:
    usage: list[decisions.DecisionUsage] = []
    started = time.monotonic()
    try:
        verdicts = competitors.confirm_competitors(run.team_id, run.site, run.brands, usage=usage)
    except decisions.DecisionError as error:
        return ModelDecisions(
            model=settings.AEO_DECISION_MODEL,
            provider="posthog",
            decisions={},
            probabilities={},
            latency_seconds=time.monotonic() - started,
            input_tokens=sum(u.input_tokens for u in usage) or None,
            output_tokens=None,
            cost_usd=None,
            error=str(error),
        )
    return ModelDecisions(
        model=settings.AEO_DECISION_MODEL,
        provider="posthog",
        decisions={v.brand.domain: v.is_competitor for v in verdicts},
        probabilities={v.brand.domain: round(v.probability, 4) for v in verdicts},
        latency_seconds=time.monotonic() - started,
        input_tokens=sum(u.input_tokens for u in usage),
        output_tokens=0,
        cost_usd=None,
    )


def claude_decisions(run: ShadowRun) -> ModelDecisions:
    started = time.monotonic()
    try:
        answer = competitors.confirm_competitors_with_claude(run.team_id, run.site, run.brands)
    except competitors.ClaudeConfirmationError as error:
        return ModelDecisions(
            model=competitors.claude_model(),
            provider="anthropic",
            decisions={},
            probabilities={},
            latency_seconds=time.monotonic() - started,
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            error=str(error),
        )
    return ModelDecisions(
        model=answer.model,
        provider="anthropic",
        decisions=dict(answer.decisions),
        probabilities={},
        latency_seconds=time.monotonic() - started,
        input_tokens=answer.input_tokens,
        output_tokens=answer.output_tokens,
        cost_usd=answer.cost_usd,
    )


def shadow_models(run: ShadowRun) -> list[ModelDecisions]:
    """Every model the live path did not use. The heuristic is not a model, so both run behind it."""
    found: list[ModelDecisions] = []
    if run.live_model != LIVE_JEV:
        found.append(jev_decisions(run))
    found.append(claude_decisions(run))
    return found


def generation_properties(run: ShadowRun, result: ModelDecisions, *, role: str) -> dict[str, Any]:
    """The `$ai_generation` properties for one model's decisions on one read. The decision per brand is in
    `$ai_output_choices` for the LLM analytics UI and in `aeo_decisions` for HogQL."""
    brands = [{"name": b.name, "domain": b.domain} for b in run.brands]
    properties: dict[str, Any] = {
        "$ai_trace_id": run.trace_id,
        "$ai_span_id": str(uuid.uuid5(uuid.UUID(run.trace_id), f"{result.model}:{role}")),
        "$ai_span_name": SPAN_NAME,
        "$ai_model": result.model,
        "$ai_provider": result.provider,
        "$ai_latency": round(result.latency_seconds, 3),
        "$ai_input": [{"role": "user", "content": {"site": dict(run.site), "brands": brands}}],
        "$ai_output_choices": [
            {
                "role": "assistant",
                "content": [
                    {
                        "domain": b.domain,
                        "competitor": result.decisions.get(b.domain),
                        "p": result.probabilities.get(b.domain),
                    }
                    for b in run.brands
                ],
            }
        ],
        "$ai_is_error": result.error is not None,
        "aeo_feature": competitors.FEATURE,
        "aeo_role": role,
        "aeo_live_model": run.live_model,
        "aeo_decisions": dict(result.decisions),
        "aeo_brand_count": len(run.brands),
        "aeo_site": run.site.get("site", ""),
    }
    if result.input_tokens is not None:
        properties["$ai_input_tokens"] = result.input_tokens
    if result.output_tokens is not None:
        properties["$ai_output_tokens"] = result.output_tokens
    if result.cost_usd is not None:
        properties["$ai_total_cost_usd"] = round(result.cost_usd, 6)
    if result.error is not None:
        properties["$ai_error"] = result.error[:500]
    return properties


def live_result(run: ShadowRun) -> ModelDecisions:
    return ModelDecisions(
        model=run.live_model if run.live_model == LIVE_HEURISTIC else settings.AEO_DECISION_MODEL,
        provider="posthog",
        decisions=dict(run.live_decisions),
        probabilities={},
        latency_seconds=0.0,
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
    )


def run_shadow(run: ShadowRun) -> None:
    """Run the other models and capture one event per model, the live decision included. A capture failure
    is logged and does not stop the other events."""
    results = [(live_result(run), "live"), *((result, "shadow") for result in shadow_models(run))]
    now = dt.datetime.now(dt.UTC)
    for result, role in results:
        try:
            capture_ai_internal_for_team(
                team_id=run.team_id,
                event_name="$ai_generation",
                event_source=EVENT_SOURCE,
                distinct_id=team_distinct_id(run.team_id),
                timestamp=now,
                properties=generation_properties(run, result, role=role),
                process_person_profile=False,
            )
        except CaptureInternalError:
            logger.warning("aeo_shadow_capture_failed", team_id=run.team_id, model=result.model, exc_info=True)


def capture_brand_reviewed(
    team_id: int,
    *,
    domain: str,
    name: str,
    kind: str,
    status: str,
    previous_kind: str,
    previous_status: str,
) -> None:
    """A person's verdict on a brand, captured in the team's project with the latest shadow trace, so each
    model's call on that brand can be scored against it. Never raises."""
    try:
        capture_internal(
            token=get_team_api_token(team_id),
            event_name=BRAND_REVIEWED_EVENT,
            event_source=EVENT_SOURCE,
            distinct_id=team_distinct_id(team_id),
            properties={
                "aeo_brand_domain": domain,
                "aeo_brand_name": name,
                "aeo_brand_kind": kind,
                "aeo_brand_status": status,
                "aeo_is_competitor": kind == "competitor" and status != "ignored",
                "aeo_previous_kind": previous_kind,
                "aeo_previous_status": previous_status,
                "aeo_shadow_trace_id": latest_trace_id(team_id),
                "$process_person_profile": False,
            },
        ).raise_for_status()
    except Exception:
        logger.warning("aeo_brand_reviewed_capture_failed", team_id=team_id, exc_info=True)
