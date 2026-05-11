"""
Per-team cache of InsightVariable lists.

The insight list/retrieve endpoints attach the full list of insight variables
for the team to the serializer context on every request, where it feeds
map_stale_to_latest and variables_override_requested_by_client. The list
changes rarely, so we cache it per team in Redis and invalidate via signals
on InsightVariable writes.

Signal handlers live in posthog/storage/insight_variable_cache_signal_handlers.py.
"""

from __future__ import annotations

from django.core.cache import cache

import structlog

from posthog.models.insight_variable import InsightVariable

logger = structlog.get_logger(__name__)

INSIGHT_VARIABLES_CACHE_TTL = 300
CACHE_KEY_PREFIX = "posthog:insight_variables:v1:team:"


def _cache_key(team_id: int) -> str:
    return f"{CACHE_KEY_PREFIX}{team_id}"


def get_insight_variables_for_team(team_id: int) -> list[InsightVariable]:
    key = _cache_key(team_id)
    try:
        cached = cache.get(key)
        if cached is not None:
            return cached
    except Exception:
        logger.warning("insight_variables_cache_get_error", team_id=team_id, exc_info=True)

    variables = list(InsightVariable.objects.filter(team_id=team_id))
    try:
        cache.set(key, variables, timeout=INSIGHT_VARIABLES_CACHE_TTL)
    except Exception:
        logger.warning("insight_variables_cache_set_error", team_id=team_id, exc_info=True)
    return variables


def invalidate_insight_variables_for_team(team_id: int) -> None:
    key = _cache_key(team_id)
    try:
        cache.delete(key)
    except Exception:
        logger.warning("insight_variables_cache_delete_error", team_id=team_id, exc_info=True)
