"""The scan slot: one query's analysis, keyed by its cache key and the flag's thresholds.

Claimed by the trigger, written once by the job, read by every response for that cache key, in the
query cache's Redis. The thresholds and the slot version ride in the key, so an analysis run under
other gates, or written by older code, lives under another key and expires on its own instead of
blocking the claim. A read returns None on any Redis or JSON failure, and a write logs and swallows.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from posthog.schema import QueryScanAnalysis

from posthog.dataclasses import frozen
from posthog.query_cache.storage import query_cache_raw_client

logger = structlog.get_logger(__name__)

# Bumped when a stored slot can no longer be read by this code. It is part of the key: a claim
# cannot replace an existing key, so an old slot left under the same key would block re-analysis
# for its whole TTL while reading as absent.
SLOT_VERSION = 2

PENDING_TTL_SECONDS = 10 * 60
DONE_TTL_SECONDS = 30 * 24 * 60 * 60

# The job runs on a queue sized to protect ClickHouse, so one project whose dashboards are all
# slow must not be able to fill it.
ENQUEUE_CAP_PER_WINDOW = 10
ENQUEUE_WINDOW_SECONDS = 60


@frozen
class QueryScanSlot:
    """One query's slot: the analysis once the job stored it, None while the job runs."""

    analysis: QueryScanAnalysis | None = None


def slot_key(team_id: int, cache_key: str, thresholds: str) -> str:
    return f"query_scan:v{SLOT_VERSION}:{team_id}:{cache_key}:{thresholds}"


def enqueue_counter_key(team_id: int) -> str:
    return f"query_scan:enqueues:{team_id}"


def get(team_id: int, cache_key: str, *, thresholds: str) -> QueryScanSlot | None:
    """The stored slot for these thresholds, or None. An analysis run under other gates lives under
    another key, so the next slow run analyzes again instead of serving it.
    """
    try:
        # The primary, not the read replica the query cache reads through. The response that
        # enqueues a scan reads the slot back in the same request, so a replica behind the write
        # would miss it.
        raw = query_cache_raw_client().get(slot_key(team_id, cache_key, thresholds))
        if raw is None:
            return None
        return _deserialize(json.loads(raw))
    except Exception:
        logger.warning("query_scan_slot_read_failed", team_id=team_id, exc_info=True)
        return None


def set_pending(team_id: int, cache_key: str, *, thresholds: str) -> bool:
    """Claim the slot for one job. The write is conditional, so two slow runs of one query enqueue one job."""
    return _write(team_id, cache_key, {"pending": True}, PENDING_TTL_SECONDS, thresholds=thresholds, nx=True)


def set_done(team_id: int, cache_key: str, *, thresholds: str, analysis: QueryScanAnalysis) -> None:
    value = {"analysis": analysis.model_dump(by_alias=True, exclude_none=True)}
    _write(team_id, cache_key, value, DONE_TTL_SECONDS, thresholds=thresholds)


def clear(team_id: int, cache_key: str, *, thresholds: str) -> None:
    """Drop the slot, for a claim no job will fill; a pending slot nobody answers reads as in flight
    for its whole TTL.
    """
    try:
        query_cache_raw_client().delete(slot_key(team_id, cache_key, thresholds))
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


def _write(
    team_id: int, cache_key: str, value: dict[str, Any], ttl_seconds: int, *, thresholds: str, nx: bool = False
) -> bool:
    try:
        payload = json.dumps(value)
        key = slot_key(team_id, cache_key, thresholds)
        return bool(query_cache_raw_client().set(key, payload, ex=ttl_seconds, nx=nx))
    except Exception:
        logger.warning("query_scan_slot_write_failed", team_id=team_id, exc_info=True)
        return False


def _deserialize(value: Any) -> QueryScanSlot | None:
    if not isinstance(value, dict):
        return None
    analysis = value.get("analysis")
    if isinstance(analysis, dict):
        return QueryScanSlot(analysis=QueryScanAnalysis.model_validate(analysis))
    if value.get("pending"):
        return QueryScanSlot()
    return None
