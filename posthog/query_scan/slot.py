"""The scan slot: what the analysis job found for one query, keyed by its cache key.

The slot lives in the same Redis as the query cache. It is written once by the job and read
by every response served for that cache key, so an unchanged query is analyzed once a month
however often it is refreshed.

Neither a read nor a write may change what the person gets. A read returns None on any Redis
or JSON failure, and a write logs and swallows.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from posthog.schema import QueryScanStatus, QueryScanWarning

from posthog.dataclasses import frozen
from posthog.query_cache.storage import query_cache_raw_client

logger = structlog.get_logger(__name__)

# Bumped when a stored slot can no longer be read by this code. An older version reads as
# "no slot", so the next slow run re-analyzes instead of serving a value we cannot parse.
SLOT_VERSION = 1

PENDING_TTL_SECONDS = 10 * 60
DONE_TTL_SECONDS = 30 * 24 * 60 * 60

# The job runs on a queue sized to protect ClickHouse, so one project whose dashboards are all
# slow must not be able to fill it.
ENQUEUE_CAP_PER_WINDOW = 10
ENQUEUE_WINDOW_SECONDS = 60


@frozen
class QueryScanSlot:
    """One analysis of one query. ``pending`` carries only the enqueue time."""

    status: QueryScanStatus
    enqueued_at: str | None = None
    analyzed_at: str | None = None
    query_kind: str | None = None
    rows_read: int | None = None
    duration_ms: int | None = None
    range_share: float | None = None
    project_share: float | None = None
    explain_ok: bool | None = None
    findings: tuple[QueryScanWarning, ...] = ()
    killed: bool = False
    error_type: str | None = None
    thresholds: str | None = None


def slot_key(team_id: int, cache_key: str) -> str:
    return f"query_scan:{team_id}:{cache_key}"


def enqueue_counter_key(team_id: int) -> str:
    return f"query_scan:enqueues:{team_id}"


def get(team_id: int, cache_key: str, *, thresholds: str | None = None) -> QueryScanSlot | None:
    """The stored slot, or None when there is none to serve.

    ``thresholds`` is the fingerprint of the gates in force now. A done slot analyzed under other
    gates reads as absent, so the next slow run analyzes again; omit it to read the slot as
    stored. A pending slot is never rejected, because the job reads the current gates itself.
    """
    try:
        # The primary, not the read replica the query cache reads through. The response that
        # enqueues a scan reads the slot back in the same request, so a replica behind the write
        # would miss it.
        raw = query_cache_raw_client().get(slot_key(team_id, cache_key))
        if raw is None:
            return None
        slot = _deserialize(json.loads(raw))
        if slot is None:
            return None
        if thresholds is not None and slot.status == QueryScanStatus.DONE and slot.thresholds != thresholds:
            return None
        return slot
    except Exception:
        logger.warning("query_scan_slot_read_failed", team_id=team_id, exc_info=True)
        return None


def set_pending(team_id: int, cache_key: str, *, killed: bool = False) -> bool:
    """Claim the slot for one job, and report whether this call is the one that claimed it.

    The write is conditional, so two slow runs of the same query that both pass the read test
    still enqueue one job: the loser is told the slot already exists.
    """
    value: dict[str, Any] = {"status": "pending", "enqueued_at": _now()}
    if killed:
        # The scan endpoint answers from this slot until the job finishes, so a run ClickHouse
        # stopped must not read as one that completed.
        value["killed"] = True
    return _write(team_id, cache_key, value, PENDING_TTL_SECONDS, nx=True)


def set_done(team_id: int, cache_key: str, slot: QueryScanSlot) -> None:
    _write(team_id, cache_key, _serialize(slot), DONE_TTL_SECONDS)


def clear(team_id: int, cache_key: str) -> None:
    """Drop the slot, for a claim no job is coming to fill.

    A pending slot nobody answers reads as an analysis in flight for its whole TTL, so the
    response reports `pending`, the scan endpoint reports `pending`, and the next slow run of
    the same query is told the slot already exists.
    """
    try:
        query_cache_raw_client().delete(slot_key(team_id, cache_key))
    except Exception:
        logger.warning("query_scan_slot_clear_failed", team_id=team_id, exc_info=True)


def claim_enqueue_budget(team_id: int) -> bool:
    """Whether this project may enqueue another scan in the current window.

    One dashboard refresh can produce hundreds of distinct slow queries, so without a cap one
    project can take the whole analytics queue. A Redis failure allows the enqueue, because the
    slot claim that follows reads the same client and stops there instead.
    """
    try:
        client = query_cache_raw_client()
        key = enqueue_counter_key(team_id)
        # An `INCR` that creates the key and a later `EXPIRE` can be split by a worker that dies,
        # and the counter left behind has no TTL, so the project stays capped for good.
        client.set(key, 0, nx=True, ex=ENQUEUE_WINDOW_SECONDS)
        count = client.incr(key)
        return count <= ENQUEUE_CAP_PER_WINDOW
    except Exception:
        logger.warning("query_scan_enqueue_budget_failed", team_id=team_id, exc_info=True)
        return True


def _write(team_id: int, cache_key: str, value: dict[str, Any], ttl_seconds: int, *, nx: bool = False) -> bool:
    try:
        payload = json.dumps({"version": SLOT_VERSION, **value})
        return bool(query_cache_raw_client().set(slot_key(team_id, cache_key), payload, ex=ttl_seconds, nx=nx))
    except Exception:
        logger.warning("query_scan_slot_write_failed", team_id=team_id, exc_info=True)
        return False


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _serialize(slot: QueryScanSlot) -> dict[str, Any]:
    value: dict[str, Any] = {
        "status": str(slot.status),
        "analyzed_at": slot.analyzed_at or _now(),
        "query_kind": slot.query_kind,
        "rows_read": slot.rows_read,
        "duration_ms": slot.duration_ms,
        "range_share": slot.range_share,
        "project_share": slot.project_share,
        "explain_ok": slot.explain_ok,
        "findings": [finding.model_dump(by_alias=True, exclude_none=True) for finding in slot.findings],
        "thresholds": slot.thresholds,
    }
    if slot.killed:
        value["killed"] = True
    if slot.error_type is not None:
        value["error_type"] = slot.error_type
    return value


def _deserialize(value: Any) -> QueryScanSlot | None:
    if not isinstance(value, dict) or value.get("version") != SLOT_VERSION:
        return None
    status = value.get("status")
    if status not in (QueryScanStatus.PENDING, QueryScanStatus.DONE):
        return None
    findings = value.get("findings")
    return QueryScanSlot(
        status=QueryScanStatus(status),
        enqueued_at=value.get("enqueued_at"),
        analyzed_at=value.get("analyzed_at"),
        query_kind=value.get("query_kind"),
        rows_read=value.get("rows_read"),
        duration_ms=value.get("duration_ms"),
        range_share=value.get("range_share"),
        project_share=value.get("project_share"),
        explain_ok=value.get("explain_ok"),
        findings=tuple(QueryScanWarning.model_validate(finding) for finding in findings)
        if isinstance(findings, list)
        else (),
        killed=bool(value.get("killed", False)),
        error_type=value.get("error_type"),
        thresholds=value.get("thresholds"),
    )
