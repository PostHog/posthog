"""Why the latest scheduled clustering run produced no run for a team.

The clustering compute activities skip a team that has too few embedded items, and that skip
writes no clustering event. The clusters page reads this record to explain the empty state.
The record lives in the Django cache, so it expires on its own when no run looks at the team.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

ClusteringLevel = Literal["trace", "generation", "evaluation"]

# Runs are daily and sample teams at random, so keep a record across a few skipped days.
SKIP_STATUS_TTL = timedelta(days=7)


@frozen
class ClusteringSkipStatus:
    item_count: int
    min_required: int
    checked_at: str


def _cache_key(team_id: int, analysis_level: ClusteringLevel) -> str:
    return f"llma_clustering_skip_status:{team_id}:{analysis_level}"


def record_not_enough_items(team_id: int, analysis_level: ClusteringLevel, item_count: int, min_required: int) -> None:
    value = {
        "item_count": item_count,
        "min_required": min_required,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    try:
        cache.set(_cache_key(team_id, analysis_level), value, timeout=int(SKIP_STATUS_TTL.total_seconds()))
    except Exception:
        # The record only explains an empty state, so a cache failure must not fail the run.
        logger.warning("Failed to record clustering skip status", team_id=team_id, exc_info=True)


def clear_skip_status(team_id: int, analysis_level: ClusteringLevel) -> None:
    try:
        cache.delete(_cache_key(team_id, analysis_level))
    except Exception:
        logger.warning("Failed to clear clustering skip status", team_id=team_id, exc_info=True)


def get_skip_status(team_id: int, analysis_level: ClusteringLevel) -> ClusteringSkipStatus | None:
    value = cache.get(_cache_key(team_id, analysis_level))
    if not isinstance(value, dict):
        return None
    try:
        return ClusteringSkipStatus(
            item_count=int(value["item_count"]),
            min_required=int(value["min_required"]),
            checked_at=str(value["checked_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
