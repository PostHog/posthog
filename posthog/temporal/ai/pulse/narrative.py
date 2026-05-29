"""LLM narrative enrichment for Pulse findings."""

import json
import asyncio
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser

from posthog.models import OrganizationMembership, Team, User
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.pulse.types import EnrichedFinding, Finding, run_trends_query_sync

from ee.hogai.llm import MaxChatOpenAI

logger = structlog.get_logger(__name__)


ATTRIBUTION_PROPERTY_CANDIDATES = [
    "$browser",
    "$os",
    "$device_type",
    "$geoip_country_name",
    "$referring_domain",
]

ENRICHMENT_CONCURRENCY = 5
ATTRIBUTION_CONCURRENCY = 5

# Narrative-only LLM: deterministic backbone does detection, the model just writes prose.
NARRATIVE_MODEL = "gpt-5-mini"
NARRATIVE_MAX_TOKENS = 200
NARRATIVE_TIMEOUT_SECONDS = 45.0


def _resolve_service_user(team: Team, user_id: int | None) -> User:
    """Resolve the user MaxChatOpenAI bills/attributes the narrative to.

    Pulse runs without a request, so we pick the subscription creator (passed as
    user_id) and fall back to an org admin. MaxChatOpenAI requires a User even with
    inject_context=False (it reads team.id, not the user, for $ai_generation).
    """
    if user_id is not None:
        user = User.objects.filter(id=user_id).first()
        if user is not None:
            return user
    admin = (
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id, level=OrganizationMembership.Level.ADMIN
        )
        .select_related("user")
        .first()
    )
    if admin is None:
        raise ValueError(f"No service user available for Pulse narrative on team {team.id}")
    return admin.user


NARRATIVE_SYSTEM_PROMPT = """You are PostHog Pulse, summarizing one metric change for a product team in 1-2 short sentences.

Rules:
- Lead with what changed and by how much, using a percentage. Example: "$pageview is down 22% this week (3,400 vs 4,350 baseline)."
- If an attribution breakdown is provided, say which segment drove the change in plain English.
- Stay factual. No speculation about causes or recommendations.
- Plain English. No jargon, no emoji, no markdown.
- Maximum 2 sentences total.
""".strip()


def _build_breakdown_query(base_query: dict, breakdown_property: str) -> dict:
    query = json.loads(json.dumps(base_query))  # deep copy
    query["dateRange"] = {"date_from": "-14d", "date_to": None}
    query["interval"] = "week"
    query["breakdownFilter"] = {"breakdown": breakdown_property, "breakdown_type": "event"}
    return query


def _pick_top_contributor(result: Any) -> tuple[str, float, float] | None:
    """Find the breakdown value with the largest week-over-week delta."""
    if not isinstance(result, dict):
        return None
    series = result.get("results") or []
    best: tuple[str, float, float] | None = None
    best_delta = 0.0
    for s in series:
        if not isinstance(s, dict):
            continue
        data = s.get("data") or []
        if len(data) < 2:
            continue
        try:
            current = float(data[-1])
            prior = float(data[-2])
        except (TypeError, ValueError):
            continue
        delta = abs(current - prior)
        if delta > best_delta:
            best_delta = delta
            best = (str(s.get("breakdown_value") or s.get("label") or "unknown"), current, prior)
    return best


async def _attribute_finding(
    team: Team, finding: Finding, attribution_semaphore: asyncio.Semaphore
) -> dict[str, Any] | None:
    async def _try_property(prop: str) -> tuple[str, dict[str, Any]] | None:
        async with attribution_semaphore:
            try:
                result = await run_trends_query_sync(team, _build_breakdown_query(finding.descriptor.query, prop))
            except Exception as exc:
                logger.exception(
                    "pulse_attribution_breakdown_failed",
                    team_id=team.id,
                    metric=finding.descriptor.label,
                    property=prop,
                    error=str(exc),
                )
                return None
            top = _pick_top_contributor(result)
            if top is None:
                return None
            value, current, prior = top
            return prop, {
                "property": prop,
                "value": value,
                "current": current,
                "baseline": prior,
                "_contribution": abs(current - prior),
            }

    results = await asyncio.gather(*[_try_property(p) for p in ATTRIBUTION_PROPERTY_CANDIDATES])
    best = max(
        (r[1] for r in results if r is not None),
        key=lambda d: d["_contribution"],
        default=None,
    )
    if best is None:
        return None
    best.pop("_contribution", None)
    return best


async def _generate_narrative(team: Team, user: User, finding: Finding, attribution: dict[str, Any] | None) -> str:
    facts = {
        "metric": finding.descriptor.label,
        "current_value": round(finding.current_value, 2),
        "baseline_value": round(finding.baseline_value, 2),
        "change_pct": round(finding.change_pct, 3),
        "robust_z": round(finding.robust_z, 2),
        "attribution": attribution,
    }

    llm = MaxChatOpenAI(
        model=NARRATIVE_MODEL,
        user=user,
        team=team,
        temperature=0.2,
        max_tokens=NARRATIVE_MAX_TOKENS,
        request_timeout=NARRATIVE_TIMEOUT_SECONDS,
        streaming=False,
        disable_streaming=True,
        max_retries=3,
        billable=False,
        inject_context=False,
        posthog_properties={"ai_product": "pulse", "domain": "pulse"},
    )
    chain = llm | StrOutputParser()
    messages = [
        SystemMessage(content=NARRATIVE_SYSTEM_PROMPT),
        HumanMessage(content=f"Finding facts:\n{json.dumps(facts, default=str)}"),
    ]
    result = await chain.ainvoke(messages)
    return result.strip()


def _fallback_narrative(finding: Finding) -> str:
    direction = "up" if finding.change_pct > 0 else "down"
    return (
        f"{finding.descriptor.label} is {direction} {abs(finding.change_pct):.0%} this week "
        f"({finding.current_value:.0f} vs {finding.baseline_value:.0f} baseline)."
    )


async def _enrich_one(
    team: Team,
    user: User,
    finding: Finding,
    enrichment_semaphore: asyncio.Semaphore,
    attribution_semaphore: asyncio.Semaphore,
) -> EnrichedFinding:
    async with enrichment_semaphore:
        try:
            attribution = await _attribute_finding(team, finding, attribution_semaphore)
            narrative = await _generate_narrative(team, user, finding, attribution)
            return EnrichedFinding(
                descriptor=finding.descriptor,
                current_value=finding.current_value,
                baseline_value=finding.baseline_value,
                change_pct=finding.change_pct,
                impact=finding.impact,
                robust_z=finding.robust_z,
                attribution_breakdown=attribution,
                narrative=narrative,
            )
        except Exception as exc:
            logger.exception(
                "pulse_enrich_finding_failed",
                team_id=team.id,
                metric=finding.descriptor.label,
                error=str(exc),
            )
            return EnrichedFinding(
                descriptor=finding.descriptor,
                current_value=finding.current_value,
                baseline_value=finding.baseline_value,
                change_pct=finding.change_pct,
                impact=finding.impact,
                robust_z=finding.robust_z,
                attribution_breakdown=None,
                narrative=_fallback_narrative(finding),
            )


async def enrich_findings(
    team_id: int, user_id: int | None, findings: list[Finding], max_findings: int
) -> list[EnrichedFinding]:
    ranked = sorted(findings, key=lambda f: f.impact, reverse=True)[:max_findings]

    @database_sync_to_async
    def _resolve() -> tuple[Team, User]:
        team = Team.objects.get(id=team_id)
        user = _resolve_service_user(team, user_id)
        return team, user

    team, user = await _resolve()
    enrichment_semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)
    attribution_semaphore = asyncio.Semaphore(ATTRIBUTION_CONCURRENCY)
    return list(
        await asyncio.gather(*[_enrich_one(team, user, f, enrichment_semaphore, attribution_semaphore) for f in ranked])
    )
