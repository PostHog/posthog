"""Build JSON-serializable insight payloads for subscription delivery history.

``SubscriptionDelivery.content_snapshot`` is built in two layers so the shape
lives here only:

1. :func:`build_initial_content_snapshot` — top-level ``dashboard`` / ``insights`` /
   ``total_insight_count`` when the delivery row is created (minimal per-insight
   rows: ``id``, ``short_id``, ``name``).
2. :func:`build_insight_delivery_snapshot` — per-exported-insight payload (same
   core keys plus ``dashboard_tile_id``, ``query_hash``, cache/results fields).
   The workflow merges these into ``content_snapshot`` on finalize; keep the
   overlapping keys aligned when changing either builder.
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic_core import to_jsonable_python

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_cache_key, calculate_for_query_based_insight
from posthog.caching.fetch_from_cache import InsightResult, NothingInCacheResult
from posthog.models import Insight, Team, User
from posthog.models.subscription import Subscription

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile

logger = structlog.get_logger(__name__)


def _json_safe_value(val: Any) -> Any:
    """Coerce to JSONField-safe Python (dict/list/scalars); unknown types use fallback, not pass-through."""
    return to_jsonable_python(val, fallback=lambda x: str(x))


def build_initial_content_snapshot(subscription: Subscription) -> dict[str, Any]:
    """Skeleton ``content_snapshot`` persisted when a delivery row is created.

    Must stay consistent with the keys :func:`build_insight_delivery_snapshot`
    sets for each insight (``id``, ``short_id``, ``name``).
    """
    content_snapshot: dict[str, Any] = {
        "dashboard": None,
        "insights": [],
        "total_insight_count": 0,
    }
    if subscription.dashboard:
        content_snapshot["dashboard"] = {
            "id": subscription.dashboard.id,
            "name": subscription.dashboard.name,
        }
    if subscription.insight:
        content_snapshot["insights"] = [
            {
                "id": subscription.insight.id,
                "short_id": str(subscription.insight.short_id),
                "name": subscription.insight.name or subscription.insight.derived_name or "",
            }
        ]
    return content_snapshot


def _serialize_insight_result(result: InsightResult) -> dict[str, Any]:
    return {
        "result": result.result,
        "columns": result.columns,
        "types": result.types,
        "resolved_date_range": _json_safe_value(result.resolved_date_range),
        "last_refresh": result.last_refresh.isoformat() if result.last_refresh else None,
        "is_cached": result.is_cached,
        "timezone": result.timezone,
        "has_more": result.has_more,
        "query_status": _json_safe_value(result.query_status),
    }


def _insight_snapshot_base_metadata(*, insight: Insight, tile: DashboardTile | None) -> dict[str, Any]:
    return {
        "id": insight.id,
        "short_id": str(insight.short_id),
        "name": insight.name or insight.derived_name or "",
        "dashboard_tile_id": tile.id if tile is not None else None,
    }


def _default_query_hash(*, tile: DashboardTile | None, insight: Insight) -> str | None:
    """Best-effort hash from layout target before execution (may be replaced by ``cache_key`` later)."""
    cache_target: DashboardTile | Insight = tile if tile is not None else insight
    query_hash = calculate_cache_key(cache_target)
    if query_hash is None:
        query_hash = insight.filters_hash
    return query_hash


def _resolve_effective_query_json(insight: Insight, dashboard: Dashboard | None) -> Any | None:
    query_json = insight.get_effective_query(dashboard=dashboard)
    if query_json is None:
        query_json = insight.query
    if query_json is None:
        query_json = insight.query_from_filters
    return query_json


def _execute_and_serialize_insight_query(
    *,
    insight: Insight,
    team: Team,
    dashboard: Dashboard | None,
    user: User | None,
    query_json: Any,
) -> dict[str, Any]:
    """Run cache/calculate path and return snapshot fields to merge (``query_*`` / ``cache_key`` only)."""
    try:
        insight_result = calculate_for_query_based_insight(
            insight,
            team=team,
            dashboard=dashboard,
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            user=user,
            query_override=query_json,
        )
    except Exception as e:
        logger.exception(
            "subscription_insight_snapshot.query_failed",
            insight_id=insight.id,
            team_id=team.id,
        )
        return {
            "query_results": None,
            "cache_key": None,
            "query_error": {"type": type(e).__name__, "message": str(e)},
        }

    if isinstance(insight_result, NothingInCacheResult):
        out: dict[str, Any] = {
            "query_results": None,
            "query_error": {
                "type": "cache_miss",
                "message": "No synchronous result (async or cache-only response)",
            },
        }
        if insight_result.cache_key:
            out["query_hash"] = insight_result.cache_key
            out["cache_key"] = insight_result.cache_key
        else:
            out["cache_key"] = None
        return out

    ck = insight_result.cache_key
    out = {
        "query_results": _serialize_insight_result(insight_result),
        "cache_key": ck,
    }
    if ck:
        out["query_hash"] = ck
    return out


def build_insight_delivery_snapshot(
    *,
    insight: Insight,
    team: Team,
    dashboard: Dashboard | None,
    tile: DashboardTile | None,
    user: User | None,
) -> dict[str, Any]:
    """Metadata + query hash + serialized query results for one exported insight.

    Core fields (``id``, ``short_id``, ``name``) match :func:`build_initial_content_snapshot`
    so workflow merges do not contradict the row created at delivery start.
    """
    base = _insight_snapshot_base_metadata(insight=insight, tile=tile)
    base["query_hash"] = _default_query_hash(tile=tile, insight=insight)

    query_json = _resolve_effective_query_json(insight, dashboard)
    if query_json is None:
        base["query_results"] = None
        base["cache_key"] = None
        base["query_error"] = {
            "type": "missing_query",
            "message": "Insight has no query or convertible filters",
        }
        return base

    base.update(
        _execute_and_serialize_insight_query(
            insight=insight,
            team=team,
            dashboard=dashboard,
            user=user,
            query_json=query_json,
        )
    )
    return base
