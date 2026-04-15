"""Build JSON-serializable insight payloads for subscription delivery history."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from pydantic import BaseModel

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_cache_key, calculate_for_query_based_insight
from posthog.caching.fetch_from_cache import InsightResult, NothingInCacheResult
from posthog.models import Insight, Team, User

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile

logger = structlog.get_logger(__name__)


def _json_safe_value(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, BaseModel):
        return _json_safe_value(val.model_dump(mode="json"))
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, dict):
        return {str(k): _json_safe_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_json_safe_value(v) for v in val]
    return val


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


def build_insight_delivery_snapshot(
    *,
    insight: Insight,
    team: Team,
    dashboard: Dashboard | None,
    tile: DashboardTile | None,
    user: User | None,
) -> dict[str, Any]:
    """Metadata + query hash + serialized query results for one exported insight."""
    base: dict[str, Any] = {
        "id": insight.id,
        "short_id": str(insight.short_id),
        "name": insight.name or insight.derived_name or "",
        "dashboard_tile_id": tile.id if tile is not None else None,
    }

    cache_target: DashboardTile | Insight = tile if tile is not None else insight
    query_hash = calculate_cache_key(cache_target)
    if query_hash is None:
        query_hash = insight.filters_hash
    base["query_hash"] = query_hash

    query_json = insight.get_effective_query(dashboard=dashboard)
    if query_json is None:
        query_json = insight.query
    if query_json is None:
        query_json = insight.query_from_filters

    if query_json is None:
        base["query_results"] = None
        base["cache_key"] = None
        base["query_error"] = {
            "type": "missing_query",
            "message": "Insight has no query or convertible filters",
        }
        return base

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
        base["query_results"] = None
        base["cache_key"] = None
        base["query_error"] = {"type": type(e).__name__, "message": str(e)}
        return base

    if isinstance(insight_result, NothingInCacheResult):
        base["query_results"] = None
        base["query_error"] = {
            "type": "cache_miss",
            "message": "No synchronous result (async or cache-only response)",
        }
        if insight_result.cache_key:
            base["query_hash"] = insight_result.cache_key
            base["cache_key"] = insight_result.cache_key
        else:
            base["cache_key"] = None
        return base

    base["query_results"] = _serialize_insight_result(insight_result)
    ck = insight_result.cache_key
    base["cache_key"] = ck
    if ck:
        base["query_hash"] = ck
    return base
