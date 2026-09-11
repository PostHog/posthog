"""The scan slot: what the job found for one query, keyed by its cache key.

Written once by the job, read by every response for that cache key, in the query cache's Redis. A
read returns None on any Redis or JSON failure, and a write logs and swallows.
"""

from __future__ import annotations

import json
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
    """One analysis of one query. A ``pending`` slot carries only the status and ``killed``."""

    status: QueryScanStatus
    range_share: float | None = None
    project_share: float | None = None
    findings: tuple[QueryScanWarning, ...] = ()
    killed: bool = False
    thresholds: str | None = None


def slot_key(team_id: int, cache_key: str) -> str:
    return f"query_scan:{team_id}:{cache_key}"


def enqueue_counter_key(team_id: int) -> str:
    return f"query_scan:enqueues:{team_id}"


def get(team_id: int, cache_key: str, *, thresholds: str | None = None) -> QueryScanSlot | None:
    """The stored slot, or None. A done slot analyzed under other gates than ``thresholds`` reads as
    absent, so the next slow run analyzes again; a pending slot is never rejected.
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
    """Claim the slot for one job. The write is conditional, so two slow runs of one query enqueue one job."""
    value: dict[str, Any] = {"status": "pending"}
    if killed:
        # The scan endpoint answers from this slot until the job finishes, so a run ClickHouse
        # stopped must not read as one that completed.
        value["killed"] = True
    return _write(team_id, cache_key, value, PENDING_TTL_SECONDS, nx=True)


def set_done(team_id: int, cache_key: str, slot: QueryScanSlot) -> None:
    _write(team_id, cache_key, _serialize(slot), DONE_TTL_SECONDS)


def clear(team_id: int, cache_key: str) -> None:
    """Drop the slot, for a claim no job is coming to fill; a pending slot nobody answers reads as in
    flight for its whole TTL.
    """
    try:
        query_cache_raw_client().delete(slot_key(team_id, cache_key))
    except Exception:
        logger.warning("query_scan_slot_clear_failed", team_id=team_id, exc_info=True)


def claim_enqueue_budget(team_id: int) -> bool:
    """Whether this project may enqueue another scan in the window. One dashboard refresh can produce
    hundreds of slow queries. A Redis failure allows the enqueue; the slot claim that follows stops
    there instead.
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


def _serialize(slot: QueryScanSlot) -> dict[str, Any]:
    value: dict[str, Any] = {
        "status": str(slot.status),
        "range_share": slot.range_share,
        "project_share": slot.project_share,
        "findings": [finding.model_dump(by_alias=True, exclude_none=True) for finding in slot.findings],
        "thresholds": slot.thresholds,
    }
    if slot.killed:
        value["killed"] = True
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
        range_share=value.get("range_share"),
        project_share=value.get("project_share"),
        findings=tuple(QueryScanWarning.model_validate(finding) for finding in findings)
        if isinstance(findings, list)
        else (),
        killed=bool(value.get("killed", False)),
        thresholds=value.get("thresholds"),
    )
