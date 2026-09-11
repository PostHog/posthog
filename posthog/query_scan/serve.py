"""Put the stored analysis on a response, on a cache hit and on a fresh run alike.

The slot is read only for a response over the flag's ``floor_ms``, since none exists below it; that
keeps a Redis read off every fast query. A Redis failure drops the advice, never the results.
"""

from __future__ import annotations

from typing import Any

import structlog

from posthog.schema import QueryScanMode, QueryScanStatus, QueryScanSummary, QueryScanWarning

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.query_scan.findings import assistant_prompt
from posthog.query_scan.flag import QueryScanFlag, get_query_scan_flag
from posthog.query_scan.slot import (
    QueryScanSlot,
    get as get_slot,
)

logger = structlog.get_logger(__name__)


@frozen(eq=False)
class _SlotLookup:
    """``flag`` is the state in force now, which a cached response cannot know. ``slot`` is None
    below the floor, where nothing is stored, and when nothing was stored.
    """

    flag: QueryScanFlag | None
    slot: QueryScanSlot | None = None


def attach_scan_slot(team: Team, response: Any) -> None:
    """Fold the stored analysis into an outgoing query response, findings included."""
    try:
        summary = getattr(response, "query_scan", None)
        if summary is None:
            return
        lookup = _look_up(team, summary.duration_ms, getattr(response, "cache_key", None))
        if lookup.flag is None:
            # A cached body outlives the flag by up to a week, so a summary that survived a
            # rollback goes rather than claiming a mode nobody granted.
            response.query_scan = None
            return
        findings = apply_slot(summary, lookup.slot, lookup.flag)
        if findings and hasattr(response, "warnings"):
            response.warnings = [*(response.warnings or []), *findings]
    except Exception:
        logger.warning("query_scan_attach_failed", team_id=team.pk, exc_info=True)


def scan_summary_with_findings(team: Team, summary: dict[str, Any], cache_key: str | None) -> dict[str, Any] | None:
    """The same fold for a surface of plain dicts. Dashboard tiles never see the response's ``warnings``,
    so the findings ride on the summary. None when the flag is off.
    """
    try:
        model = QueryScanSummary.model_validate(summary)
        lookup = _look_up(team, model.duration_ms, cache_key)
        if lookup.flag is None:
            return None
        findings = apply_slot(model, lookup.slot, lookup.flag)
        folded = model.model_dump(mode="json", by_alias=True, exclude_none=True)
        # `status` stays on the dict even when it is None, so a tile can tell an unanalyzed run apart.
        folded["status"] = folded.get("status")
        if model.status == QueryScanStatus.DONE:
            folded["warnings"] = [finding.model_dump(by_alias=True, exclude_none=True) for finding in findings]
        return folded
    except Exception:
        logger.warning("query_scan_summary_fold_failed", team_id=team.pk, exc_info=True)
        return summary


def apply_slot(summary: QueryScanSummary, slot: QueryScanSlot | None, flag: QueryScanFlag) -> list[QueryScanWarning]:
    """Correct ``summary`` against the live flag and the stored analysis, and return the findings to show.

    The cached summary carries the mode of the run that filled it, which can have moved since, and
    a status of a run whose slot has since expired. `log_only` collects the analysis without showing
    it to anyone, so its findings stay out.
    """
    summary.mode = flag.mode
    if slot is None:
        summary.status = None
        return []
    summary.status = slot.status
    if slot.status != QueryScanStatus.DONE:
        return []
    summary.range_share = slot.range_share
    summary.project_share = slot.project_share
    # `killed` describes the run behind the summary, so the run's own flag stands: the slot can hold
    # the analysis of an earlier run that was stopped while this one finished. Once the analysis is
    # in, the flag is spelled out rather than left absent.
    killed = bool(summary.killed)
    summary.killed = killed
    if flag.mode != QueryScanMode.SHOW:
        return []
    findings = list(slot.findings)
    summary.assistant_prompt = assistant_prompt(
        findings,
        rows_read=summary.rows_read,
        duration_ms=summary.duration_ms,
        range_share=slot.range_share,
        project_share=slot.project_share,
        killed=killed,
        fixable_only=True,
    )
    return findings


def _look_up(team: Team, duration_ms: int, cache_key: str | None) -> _SlotLookup:
    # The flag is resolved first because a cached summary has to be corrected against it even
    # when no slot is read. It is evaluated locally, so this costs no round trip.
    flag = get_query_scan_flag(team)
    if flag is None:
        return _SlotLookup(flag=None)
    if cache_key is None or duration_ms < flag.floor_ms:
        return _SlotLookup(flag=flag)
    return _SlotLookup(flag=flag, slot=get_slot(team.pk, cache_key, thresholds=flag.thresholds_fingerprint))
