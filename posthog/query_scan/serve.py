"""Put the stored analysis on a response, on a cache hit and on a fresh run alike.

The slot is read only for a response whose ClickHouse duration crossed the floor, because a
slot can only exist for such a run. That keeps a fleet-wide Redis read off every fast query.

Nothing here may change the response beyond the scan fields: a Redis failure drops the advice,
never the results.
"""

from __future__ import annotations

from typing import Any

import structlog

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.query_scan.flag import QueryScanFlag, get_query_scan_flag
from posthog.query_scan.slot import (
    QueryScanSlot,
    get as get_slot,
)

logger = structlog.get_logger(__name__)


@frozen(eq=False)
class _SlotLookup:
    """``over_floor`` says whether the response is one a slot could exist for, which is what
    tells an absent slot apart from a query that was never a candidate. ``flag`` is the state
    in force now, which a cached response cannot know."""

    flag: QueryScanFlag | None
    over_floor: bool
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
        # The cached body carries the mode of the run that filled it, which can have moved since.
        summary.mode = lookup.flag.mode
        if not lookup.over_floor:
            # Below the floor nothing reads the slot, so a status from the old floor cannot be
            # confirmed.
            summary.status = None
            return
        if lookup.slot is None:
            # A cached response can carry the status of a run whose slot has since expired.
            summary.status = None
            return
        summary.status = lookup.slot.status
        if lookup.slot.status != "done":
            return
        summary.range_share = lookup.slot.range_share
        summary.project_share = lookup.slot.project_share
        # `log_only` collects the analysis without showing it to anyone.
        if lookup.flag.mode == "show" and lookup.slot.findings and hasattr(response, "warnings"):
            response.warnings = [*(response.warnings or []), *lookup.slot.findings]
    except Exception:
        logger.warning("query_scan_attach_failed", team_id=team.pk, exc_info=True)


def scan_summary_with_findings(team: Team, summary: dict[str, Any], cache_key: str | None) -> dict[str, Any] | None:
    """The same fold for a surface that carries plain dicts rather than the response model.

    Dashboard tiles never see the response's ``warnings`` list, so the findings ride on the
    summary itself. None when the flag is off, which is how the tile shows nothing.
    """
    try:
        lookup = _look_up(team, summary.get("duration_ms"), cache_key)
        if lookup.flag is None:
            return None
        summary = {**summary, "mode": lookup.flag.mode}
        if not lookup.over_floor:
            return {**summary, "status": None}
        if lookup.slot is None:
            return {**summary, "status": None}
        folded = {**summary, "status": str(lookup.slot.status)}
        if lookup.slot.status == "done":
            folded["range_share"] = lookup.slot.range_share
            folded["project_share"] = lookup.slot.project_share
            findings = lookup.slot.findings if lookup.flag.mode == "show" else ()
            folded["warnings"] = [finding.model_dump(by_alias=True, exclude_none=True) for finding in findings]
        return folded
    except Exception:
        logger.warning("query_scan_summary_fold_failed", team_id=team.pk, exc_info=True)
        return summary


def _look_up(team: Team, duration_ms: Any, cache_key: str | None) -> _SlotLookup:
    # The flag is resolved first because a cached summary has to be corrected against it even
    # when no slot is read. It is cached in-process, so this costs no round trip.
    flag = get_query_scan_flag(team)
    if flag is None:
        return _SlotLookup(flag=None, over_floor=False)
    if cache_key is None or not isinstance(duration_ms, int) or duration_ms < flag.floor_ms:
        return _SlotLookup(flag=flag, over_floor=False)
    return _SlotLookup(
        flag=flag, over_floor=True, slot=get_slot(team.pk, cache_key, thresholds=flag.thresholds_fingerprint)
    )
