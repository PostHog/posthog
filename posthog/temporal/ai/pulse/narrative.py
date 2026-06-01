"""LLM narrative enrichment for Pulse findings."""

import json
import asyncio
import statistics
from datetime import datetime
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser

from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL
from posthog.models import OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.annotation import Annotation
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.pulse.detection import MAX_BASELINE_WEEKS, MIN_BASELINE_WEEKS
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

# Breakdown placeholders that don't name a real segment — never a meaningful attribution or
# a worthwhile replay lookup. A property that's mostly unset makes its null bucket the biggest
# mover, so skipping these keeps attribution on a real segment.
SYNTHETIC_BREAKDOWN_VALUES = {"Other", "unknown", "", BREAKDOWN_OTHER_STRING_LABEL, BREAKDOWN_NULL_STRING_LABEL}

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
    # Match the detection window so attribution compares the same completed-week-vs-baseline.
    query["dateRange"] = {"date_from": "-42d", "date_to": None}
    query["interval"] = "week"
    query["breakdownFilter"] = {"breakdown": breakdown_property, "breakdown_type": "event"}
    return query


def _pick_top_contributor(result: Any) -> tuple[str, float, float] | None:
    """Find the breakdown value that contributed most to the change.

    Mirrors detection: drop the in-progress (partial) week, compare the last completed week to the
    median of the prior completed weeks, and skip synthetic ("Other"/"no value") buckets — otherwise
    a mostly-unset property makes its null bucket the biggest mover.
    """
    if not isinstance(result, dict):
        return None
    series = result.get("results") or []
    best: tuple[str, float, float] | None = None
    best_delta = 0.0
    for s in series:
        if not isinstance(s, dict):
            continue
        value = str(s.get("breakdown_value") or s.get("label") or "unknown")
        if value in SYNTHETIC_BREAKDOWN_VALUES:
            continue
        data = [float(v) for v in (s.get("data") or []) if isinstance(v, int | float) and not isinstance(v, bool)]
        if len(data) < MIN_BASELINE_WEEKS + 2:
            continue
        completed = data[:-1]  # drop the partial current week
        current = completed[-1]
        baseline = completed[:-1][-MAX_BASELINE_WEEKS:]
        if len(baseline) < MIN_BASELINE_WEEKS:
            continue
        baseline_median = statistics.median(baseline)
        delta = abs(current - baseline_median)
        if delta > best_delta:
            best_delta = delta
            best = (value, current, baseline_median)
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


REPLAY_EVIDENCE_LIMIT = 3


def _finding_event(finding: Finding) -> str | None:
    """Pull the headline event name out of the finding's TrendsQuery-shaped descriptor, if it has one."""
    series = finding.descriptor.query.get("series") or []
    if not series or not isinstance(series[0], dict):
        return None
    event = series[0].get("event")
    return event if isinstance(event, str) and event else None


def _query_session_ids(
    team: Team, event_name: str, prop_key: str, prop_value: Any, date_from: str, date_to: str
) -> list[str]:
    """Up to REPLAY_EVIDENCE_LIMIT session ids where `event_name` fired with `prop_key=prop_value`.

    Synchronous — executes a ClickHouse query — so it is only ever called via database_sync_to_async.
    """
    # Lazy import: the pulse package is eagerly preloaded via posthog.api; importing the recordings
    # query layer at module level risks an app-init circular import (see selection.py / delivery.py).
    from posthog.schema import RecordingOrder, RecordingsQuery

    from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

    query = RecordingsQuery(
        events=[
            {
                "id": event_name,
                "name": event_name,
                "type": "events",  # entity type is plural
                "properties": [
                    {
                        "type": "event",
                        "key": prop_key,
                        "value": prop_value,
                        "operator": "exact",
                    },  # property type is singular
                ],
            }
        ],
        date_from=date_from,
        date_to=date_to,
        limit=REPLAY_EVIDENCE_LIMIT,
        filter_test_accounts=True,
        order=RecordingOrder.START_TIME,
    )
    result = SessionRecordingListFromQuery(team=team, query=query, max_execution_time=30).run()
    return [sid for row in result.results[:REPLAY_EVIDENCE_LIMIT] if (sid := row.get("session_id"))]


async def _collect_replay_evidence(
    team: Team, finding: Finding, attribution: dict[str, Any] | None, period_start: str, period_end: str
) -> list[str]:
    """Find a few example replay session ids for the segment that drove the change.

    Targeted: only runs when there is a concrete attribution segment (a headline event plus a real,
    non-synthetic breakdown value) and a period window. Best-effort — degrades to [] on any error or
    zero matches, which is common (sampling, retention, server-side events).
    """
    if not attribution or not period_start or not period_end:
        return []
    prop_key = attribution.get("property")
    prop_value = attribution.get("value")
    if not prop_key or prop_value is None or str(prop_value) in SYNTHETIC_BREAKDOWN_VALUES:
        return []
    event_name = _finding_event(finding)
    if not event_name:
        return []
    try:
        date_from = datetime.fromisoformat(period_start).date().isoformat()
        date_to = datetime.fromisoformat(period_end).date().isoformat()
        return await database_sync_to_async(_query_session_ids, thread_sensitive=False)(
            team, event_name, prop_key, prop_value, date_from, date_to
        )
    except Exception as exc:
        logger.warning("pulse_replay_evidence_failed", team_id=team.id, metric=finding.descriptor.label, error=str(exc))
        return []


async def _enrich_one(
    team: Team,
    user: User,
    finding: Finding,
    enrichment_semaphore: asyncio.Semaphore,
    attribution_semaphore: asyncio.Semaphore,
    period_start: str = "",
    period_end: str = "",
) -> EnrichedFinding:
    async with enrichment_semaphore:
        # Attribution and evidence are independent of the narrative LLM, so collect them first and
        # keep them even if narrative generation falls back.
        attribution: dict[str, Any] | None = None
        session_ids: list[str] = []
        try:
            attribution = await _attribute_finding(team, finding, attribution_semaphore)
            session_ids = await _collect_replay_evidence(team, finding, attribution, period_start, period_end)
            narrative = await _generate_narrative(team, user, finding, attribution)
            if not narrative:  # empty LLM response (e.g. no model configured) — keep a useful line
                narrative = _fallback_narrative(finding)
        except Exception as exc:
            logger.exception(
                "pulse_enrich_finding_failed",
                team_id=team.id,
                metric=finding.descriptor.label,
                error=str(exc),
            )
            narrative = _fallback_narrative(finding)
        return EnrichedFinding(
            descriptor=finding.descriptor,
            current_value=finding.current_value,
            baseline_value=finding.baseline_value,
            change_pct=finding.change_pct,
            impact=finding.impact,
            robust_z=finding.robust_z,
            attribution_breakdown=attribution,
            evidence={"session_ids": session_ids} if session_ids else None,
            narrative=narrative,
        )


async def enrich_findings(
    team_id: int,
    user_id: int | None,
    findings: list[Finding],
    max_findings: int,
    period_start: str = "",
    period_end: str = "",
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
        await asyncio.gather(
            *[
                _enrich_one(team, user, f, enrichment_semaphore, attribution_semaphore, period_start, period_end)
                for f in ranked
            ]
        )
    )


SYNTHESIS_MAX_TOKENS = 320
MAX_FLAG_CHANGES_FOR_AI_CONTEXT = 15
MAX_NEW_ISSUES_FOR_AI_CONTEXT = 5

SYNTHESIS_SYSTEM_PROMPT = """You are PostHog Pulse, giving a product team the big-picture read across this week's flagged metric changes.

You are given several findings (metric, % change, optional attribution segment), optionally annotations (dated events the team logged — deploys, launches, incidents), optionally feature-flag changes in the same period (a flag rolled out, turned on/off), and optionally new error-tracking issues that appeared recently (name and how many times they fired). Write a short paragraph, 2-4 sentences:
- If there is an overall theme, name it (e.g. "growth signals rose while conversion softened").
- Call out metrics that moved TOGETHER as a HYPOTHESIS worth checking — e.g. "signups and pricing views both rose, possibly the same driver." Frame these as things to investigate, never as proven cause.
- If a change lines up with an annotation, note it as a possible explanation to verify — e.g. "the signup rise lines up with your 'pricing v2' note on the 20th." A coincidence to check, never proven cause.
- If a change lines up with a feature-flag change, note it as a possible explanation to verify — e.g. "the activation dip coincides with turning on the 'new-onboarding' flag — worth checking." A coincidence to check, never proven cause.
- If a metric drop lines up with a new error issue, note it as a possible explanation to verify — e.g. "checkout completions fell while a new 'Payment timeout' error appeared — worth checking if they're linked." A coincidence to check, never proven cause.
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


def _fetch_error_signals(team: Team) -> list[dict[str, Any]]:
    """New error-tracking issues seen recently, as coincident-signal context for synthesis (never causation).

    Uses the error-tracking facade's recent-new-issues query (a ~7-day window, which lines up with the
    weekly digest period). Best-effort: any failure — including ClickHouse being unavailable or the team
    not using error tracking — degrades to no signal rather than breaking the additive synthesis step.
    """
    # Lazy import: the pulse package is eagerly preloaded via posthog.api, and importing the
    # error-tracking facade at module level risks an app-init circular import (see delivery.py).
    from products.error_tracking.backend.facade import api as error_tracking_api

    try:
        issues = error_tracking_api.get_new_issues_for_team(team)
    except Exception as exc:
        logger.warning("pulse_fetch_error_signals_failed", team_id=team.id, error=str(exc))
        return []
    return [
        {
            "name": _sanitize_for_prompt(str(issue.get("name") or "Untitled issue")),
            "count": int(issue.get("occurrence_count") or 0),
        }
        for issue in issues[:MAX_NEW_ISSUES_FOR_AI_CONTEXT]
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
    def _resolve() -> tuple[Team, User, list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]]:
        team = Team.objects.get(id=team_id)
        user = _resolve_service_user(team, user_id)
        # New error issues use a ~7-day window internally, independent of the digest period bounds.
        error_signals = _fetch_error_signals(team)
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
        return team, user, annotations, flag_changes, error_signals

    team, user, annotations, flag_changes, error_signals = await _resolve()
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
        "new_error_issues": error_signals,
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
        HumanMessage(
            content=f"This period's findings, annotations, flag changes, and new error issues:\n{json.dumps(facts, default=str)}"
        ),
    ]
    try:
        result = await chain.ainvoke(messages)
        return result.strip()
    except Exception as exc:
        logger.exception("pulse_synthesize_digest_failed", team_id=team_id, error=str(exc))
        return ""
