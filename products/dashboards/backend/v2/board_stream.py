"""The `dashboard-v2` board stream: the first event of a `cached_first` stream, built from the batched cached read."""

from datetime import datetime
from typing import Any

from django.utils.timezone import now

from products.dashboards.backend.query_sharing_stream import DashboardQuerySharingCachedEvent
from products.dashboards.backend.v2.cached_tiles import CachedTileStatus


def _cached_result_is_stale(insight: dict[str, Any]) -> bool:
    # The same rule the dashboard client applies to decide which tiles to refresh.
    target_age = insight.get("cache_target_age")
    if isinstance(target_age, str):
        target_age = datetime.fromisoformat(target_age)
    return not isinstance(target_age, datetime) or target_age <= now()


def _mark_stale(entry: dict[str, Any]) -> dict[str, object]:
    if entry["status"] != CachedTileStatus.HIT:
        return entry
    return {**entry, "stale": _cached_result_is_stale(entry["insight"])}


def _needs_compute(entry: dict[str, Any], *, force: bool) -> bool:
    if entry["status"] == CachedTileStatus.MISS:
        return True
    return entry["status"] == CachedTileStatus.HIT and (force or _cached_result_is_stale(entry["insight"]))


def cached_event(cached: list[dict[str, Any]], *, force: bool) -> DashboardQuerySharingCachedEvent:
    """Every tile's cached result, stale hits included and marked, and in `pending` the tiles the stream computes
    next: the missing and stale ones, or every hit and miss when `force` is set."""
    return {
        "type": "cached",
        "tiles": [_mark_stale(entry) for entry in cached],
        "pending": [entry["id"] for entry in cached if _needs_compute(entry, force=force)],
    }
