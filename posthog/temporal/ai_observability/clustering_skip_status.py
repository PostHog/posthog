"""Why the latest scheduled clustering run produced no run for a team.

The clustering compute activities skip a team that has too few embedded items, and that skip
writes no clustering event. The clusters page reads this record to explain the empty state.
The record lives in Redis, so it expires on its own when no run looks at the team.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Literal

import redis
import structlog

from posthog.dataclasses import frozen
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

ClusteringLevel = Literal["trace", "generation", "evaluation"]

# Runs are daily and sample teams at random, so keep a record across a few skipped days.
SKIP_STATUS_TTL = timedelta(days=7)
# The compute activity and the API both call Redis inline, so a slow Redis must not stall them.
REDIS_TIMEOUT_SECONDS = 1.0


@frozen
class ClusteringSkipStatus:
    item_count: int
    min_required: int
    checked_at: str


def _cache_key(team_id: int, analysis_level: ClusteringLevel) -> str:
    return f"llma_clustering_skip_status:{team_id}:{analysis_level}"


def _redis() -> redis.Redis:
    return get_client(socket_timeout=REDIS_TIMEOUT_SECONDS, socket_connect_timeout=REDIS_TIMEOUT_SECONDS)


def record_not_enough_items(team_id: int, analysis_level: ClusteringLevel, item_count: int, min_required: int) -> None:
    value = {
        "item_count": item_count,
        "min_required": min_required,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    try:
        _redis().set(_cache_key(team_id, analysis_level), json.dumps(value), ex=SKIP_STATUS_TTL)
    except Exception:
        # The record only explains an empty state, so a Redis failure must not fail the run.
        logger.warning("Failed to record clustering skip status", team_id=team_id, exc_info=True)


def clear_skip_status(team_id: int, analysis_level: ClusteringLevel) -> None:
    try:
        _redis().delete(_cache_key(team_id, analysis_level))
    except Exception:
        logger.warning("Failed to clear clustering skip status", team_id=team_id, exc_info=True)


def clear_all_skip_statuses(team_id: int) -> None:
    """A job change makes every recorded count stale, because the counts depend on the job filters."""
    for level in ("trace", "generation", "evaluation"):
        clear_skip_status(team_id, level)


def get_skip_status(team_id: int, analysis_level: ClusteringLevel) -> ClusteringSkipStatus | None:
    try:
        raw = _redis().get(_cache_key(team_id, analysis_level))
    except Exception:
        logger.warning("Failed to read clustering skip status", team_id=team_id, exc_info=True)
        return None
    if raw is None:
        return None
    try:
        value = json.loads(raw)
        return ClusteringSkipStatus(
            item_count=int(value["item_count"]),
            min_required=int(value["min_required"]),
            checked_at=str(value["checked_at"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
