from collections.abc import Iterable
from datetime import timedelta
from typing import Optional

from django.core.cache import caches

import structlog

from posthog.caching.redis_cluster_connection_factory import QUERY_CACHE_ALIAS

logger = structlog.get_logger(__name__)

# Longer than the slowest staleness interval, so an insight that is warmed once a day keeps its record.
WARMING_COST_TTL = timedelta(days=7)

InsightContext = tuple[int, Optional[int]]


def _key(team_id: int, insight_id: int, dashboard_id: Optional[int]) -> str:
    return f"warming_cost:{team_id}:{insight_id}:{dashboard_id or ''}"


def record_warming_duration(*, team_id: int, insight_id: int, dashboard_id: Optional[int], seconds: float) -> None:
    try:
        caches[QUERY_CACHE_ALIAS].set(
            _key(team_id, insight_id, dashboard_id), round(seconds, 1), WARMING_COST_TTL.total_seconds()
        )
    except Exception:
        logger.exception("warming_cost_write_failed", team_id=team_id, insight_id=insight_id)


def record_failed_warming_duration(
    *, team_id: int, insight_id: int, dashboard_id: Optional[int], seconds: float
) -> None:
    # An open query failure circuit makes a warm fail at once, so its elapsed time says nothing about the
    # query. Keep the larger value, so that a fast replayed failure never hides the slow run before it.
    previous = get_warming_durations(team_id=team_id, contexts=[(insight_id, dashboard_id)]).get(
        (insight_id, dashboard_id), 0.0
    )
    record_warming_duration(
        team_id=team_id, insight_id=insight_id, dashboard_id=dashboard_id, seconds=max(previous, seconds)
    )


def get_warming_durations(*, team_id: int, contexts: Iterable[InsightContext]) -> dict[InsightContext, float]:
    context_by_key = {
        _key(team_id, insight_id, dashboard_id): (insight_id, dashboard_id) for insight_id, dashboard_id in contexts
    }
    if not context_by_key:
        return {}
    try:
        found = caches[QUERY_CACHE_ALIAS].get_many(list(context_by_key))
    except Exception:
        logger.exception("warming_cost_read_failed", team_id=team_id)
        return {}
    return {
        context_by_key[key]: float(seconds)
        for key, seconds in found.items()
        if isinstance(seconds, int | float) and not isinstance(seconds, bool)
    }
