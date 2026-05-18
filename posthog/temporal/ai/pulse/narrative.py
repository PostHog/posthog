"""LLM narrative enrichment for Pulse findings."""

import json
import asyncio
from typing import Any

import structlog

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.pulse.types import EnrichedFinding, Finding, run_trends_query_sync

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


async def _generate_narrative(team_id: int, finding: Finding, attribution: dict[str, Any] | None) -> str:
    # Lazy-import langchain so non-Pulse Temporal workers don't pay the startup cost.
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.output_parsers import StrOutputParser
    from langchain_openai import ChatOpenAI
    from posthoganalytics import default_client
    from posthoganalytics.ai.langchain import CallbackHandler

    facts = {
        "metric": finding.descriptor.label,
        "current_value": round(finding.current_value, 2),
        "baseline_value": round(finding.baseline_value, 2),
        "change_pct": round(finding.change_pct, 3),
        "z_score": round(finding.z_score, 2),
        "attribution": attribution,
    }

    callback_handler = CallbackHandler(
        default_client,
        properties={"domain": "pulse", "team_id": team_id},
    )
    chain = ChatOpenAI(model="gpt-4.1-mini", temperature=0.2, streaming=False, max_retries=3) | StrOutputParser()
    messages = [
        SystemMessage(content=NARRATIVE_SYSTEM_PROMPT),
        HumanMessage(content=f"Finding facts:\n{json.dumps(facts, default=str)}"),
    ]
    result = await chain.ainvoke(messages, config={"callbacks": [callback_handler]})
    return result.strip()


def _fallback_narrative(finding: Finding) -> str:
    direction = "up" if finding.change_pct > 0 else "down"
    return (
        f"{finding.descriptor.label} is {direction} {abs(finding.change_pct):.0%} this week "
        f"({finding.current_value:.0f} vs {finding.baseline_value:.0f} baseline)."
    )


async def _enrich_one(
    team: Team,
    finding: Finding,
    enrichment_semaphore: asyncio.Semaphore,
    attribution_semaphore: asyncio.Semaphore,
) -> EnrichedFinding:
    async with enrichment_semaphore:
        try:
            attribution = await _attribute_finding(team, finding, attribution_semaphore)
            narrative = await _generate_narrative(team.id, finding, attribution)
            return EnrichedFinding(
                descriptor=finding.descriptor,
                current_value=finding.current_value,
                baseline_value=finding.baseline_value,
                change_pct=finding.change_pct,
                z_score=finding.z_score,
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
                z_score=finding.z_score,
                attribution_breakdown=None,
                narrative=_fallback_narrative(finding),
            )


async def enrich_findings(team_id: int, findings: list[Finding], max_findings: int) -> list[EnrichedFinding]:
    ranked = sorted(findings, key=lambda f: abs(f.z_score), reverse=True)[:max_findings]

    @database_sync_to_async
    def _get_team() -> Team:
        return Team.objects.get(id=team_id)

    team = await _get_team()
    enrichment_semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)
    attribution_semaphore = asyncio.Semaphore(ATTRIBUTION_CONCURRENCY)
    return list(
        await asyncio.gather(
            *[_enrich_one(team, f, enrichment_semaphore, attribution_semaphore) for f in ranked]
        )
    )
