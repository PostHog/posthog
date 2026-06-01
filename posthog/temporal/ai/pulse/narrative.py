"""LLM narrative enrichment for Pulse findings."""

import json
import asyncio
from datetime import datetime
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser

from posthog.models import OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.annotation import Annotation
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


SYNTHESIS_MAX_TOKENS = 320
MAX_FLAG_CHANGES_FOR_AI_CONTEXT = 15

SYNTHESIS_SYSTEM_PROMPT = """You are PostHog Pulse, giving a product team the big-picture read across this week's flagged metric changes.

You are given several findings (metric, % change, optional attribution segment), optionally annotations (dated events the team logged — deploys, launches, incidents), and optionally feature-flag changes in the same period (a flag rolled out, turned on/off). Write a short paragraph, 2-4 sentences:
- If there is an overall theme, name it (e.g. "growth signals rose while conversion softened").
- Call out metrics that moved TOGETHER as a HYPOTHESIS worth checking — e.g. "signups and pricing views both rose, possibly the same driver." Frame these as things to investigate, never as proven cause.
- If a change lines up with an annotation, note it as a possible explanation to verify — e.g. "the signup rise lines up with your 'pricing v2' note on the 20th." A coincidence to check, never proven cause.
- If a change lines up with a feature-flag change, note it as a possible explanation to verify — e.g. "the activation dip coincides with turning on the 'new-onboarding' flag — worth checking." A coincidence to check, never proven cause.
- Stay factual and humble. Do not invent causes. No recommendations beyond "worth investigating". No jargon, emoji, or markdown.

If the findings share no obvious pattern, say that briefly rather than forcing a connection.""".strip()


def _sanitize_for_prompt(text: str) -> str:
    """Strip characters usable for prompt injection from team-authored free text (flag names, annotations)."""
    cleaned = "".join(c for c in text if c == " " or (c.isprintable() and c not in "<>"))
    return cleaned[:200]


def _describe_flag_change(activity: str, detail: dict[str, Any] | None) -> str:
    """Short human label for a FeatureFlag ActivityLog row: created / deleted / turned on / turned off / updated."""
    if activity == "created":
        return "created"
    if activity == "deleted":
        return "deleted"
    for change in (detail or {}).get("changes") or []:
        if isinstance(change, dict) and change.get("field") == "active":
            return "turned on" if change.get("after") else "turned off"
    return "updated"


def _fetch_flag_changes(team_id: int, start: datetime, end: datetime) -> list[dict[str, str]]:
    """Feature-flag mutations in the period, as coincident-signal context for synthesis (never causation).

    ActivityLog is a plain team_id-scoped model (no fail-closed manager), so a direct filter is correct.
    """
    rows = (
        ActivityLog.objects.filter(
            team_id=team_id,
            scope="FeatureFlag",
            activity__in=["created", "updated", "deleted"],
            created_at__gte=start,
            created_at__lte=end,
        )
        .order_by("created_at")
        .values_list("created_at", "activity", "detail")[:MAX_FLAG_CHANGES_FOR_AI_CONTEXT]
    )
    return [
        {
            "date": created_at.date().isoformat(),
            "flag": _sanitize_for_prompt(str((detail or {}).get("name") or "a feature flag")),
            "change": _describe_flag_change(activity, detail),
        }
        for created_at, activity, detail in rows
    ]


async def synthesize_digest(
    team_id: int,
    user_id: int | None,
    findings: list[EnrichedFinding],
    period_start: str = "",
    period_end: str = "",
) -> str:
    """Digest-level "big picture" across ALL findings — co-movement hypotheses, not per-metric prose.

    Runs once per digest (vs _generate_narrative, which is per-finding). Pulls in any team annotations
    in the period as known-event context. Returns "" when there is too little to synthesize across or
    the call fails — the summary is additive, never load-bearing.
    """
    if len(findings) < 2:
        return ""

    @database_sync_to_async
    def _resolve() -> tuple[Team, User, list[dict[str, str]], list[dict[str, str]]]:
        team = Team.objects.get(id=team_id)
        user = _resolve_service_user(team, user_id)
        annotations: list[dict[str, str]] = []
        flag_changes: list[dict[str, str]] = []
        if period_start and period_end:
            start = datetime.fromisoformat(period_start)
            end = datetime.fromisoformat(period_end)
            rows = (
                Annotation.objects.filter(
                    team_id=team_id,
                    deleted=False,
                    date_marker__gte=start,
                    date_marker__lte=end,
                )
                .order_by("date_marker")
                .values_list("date_marker", "content")[:20]
            )
            annotations = [
                {"date": dm.date().isoformat(), "note": _sanitize_for_prompt(content)}
                for dm, content in rows
                if content
            ]
            flag_changes = _fetch_flag_changes(team_id, start, end)
        return team, user, annotations, flag_changes

    team, user, annotations, flag_changes = await _resolve()
    facts = {
        "findings": [
            {
                "metric": f.descriptor.label,
                "change_pct": round(f.change_pct, 3),
                "attribution": f.attribution_breakdown,
            }
            for f in findings
        ],
        "annotations": annotations,
        "feature_flag_changes": flag_changes,
    }

    llm = MaxChatOpenAI(
        model=NARRATIVE_MODEL,
        user=user,
        team=team,
        temperature=0.3,
        max_tokens=SYNTHESIS_MAX_TOKENS,
        request_timeout=NARRATIVE_TIMEOUT_SECONDS,
        streaming=False,
        disable_streaming=True,
        max_retries=3,
        billable=False,
        inject_context=False,
        posthog_properties={"ai_product": "pulse", "domain": "pulse_synthesis"},
    )
    chain = llm | StrOutputParser()
    messages = [
        SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
        HumanMessage(content=f"This period's findings and annotations:\n{json.dumps(facts, default=str)}"),
    ]
    try:
        result = await chain.ainvoke(messages)
        return result.strip()
    except Exception as exc:
        logger.exception("pulse_synthesize_digest_failed", team_id=team_id, error=str(exc))
        return ""
