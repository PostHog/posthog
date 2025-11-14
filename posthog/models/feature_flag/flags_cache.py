"""
Flags HyperCache for feature-flags service.

This module provides a HyperCache that stores feature flags for the feature-flags service.
Unlike the local_evaluation.py cache which provides rich data for SDKs (including cohorts
and group type mappings), this cache provides just the raw flag data.

The cache is automatically invalidated when:
- FeatureFlag models are created, updated, or deleted
- Team models are created or deleted (to ensure flag caches are cleaned up)

Cache Key Pattern:
- Uses team_id as the key
- Stored in both Redis and S3 via HyperCache

Configuration:
- Redis TTL: 7 days (configurable via FLAGS_CACHE_TTL env var)
- Miss TTL: 1 day (configurable via FLAGS_CACHE_MISS_TTL env var)
"""

from typing import Any

from django.conf import settings
from django.core.cache import cache, caches
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

import structlog

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.models.feature_flag import FeatureFlag
from posthog.models.feature_flag.feature_flag import get_feature_flags, serialize_feature_flags
from posthog.models.team import Team
from posthog.storage.hypercache import HyperCache

logger = structlog.get_logger(__name__)


def _get_feature_flags_for_service(team: Team) -> dict[str, Any]:
    """
    Get feature flags for the feature-flags service.

    Fetches all active, non-deleted feature flags for the team and returns them
    wrapped in a dict that HyperCache can serialize. The actual flag data is in the
    "flags" key as a list of flag dictionaries.

    Returns:
        dict: {"flags": [...]} where flags is a list of flag dictionaries
    """
    flags = get_feature_flags(team=team)
    flags_data = serialize_feature_flags(flags)

    logger.info(
        "Loaded feature flags for service cache",
        team_id=team.id,
        project_id=team.project_id,
        flag_count=len(flags_data),
    )

    # Wrap in dict for HyperCache compatibility
    return {"flags": flags_data}


# Use dedicated flags cache if available, otherwise fall back to default cache
if FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES:
    _flags_cache_client = caches[FLAGS_DEDICATED_CACHE_ALIAS]
else:
    _flags_cache_client = cache

# HyperCache instance for feature-flags service
flags_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags.json",
    load_fn=lambda key: _get_feature_flags_for_service(HyperCache.team_from_key(key)),
    cache_ttl=settings.FLAGS_CACHE_TTL,
    cache_miss_ttl=settings.FLAGS_CACHE_MISS_TTL,
    cache_client=_flags_cache_client,
)


def get_flags_from_cache(team: Team) -> list[dict[str, Any]]:
    """
    Get feature flags from the cache for a team.

    Only operates when FLAGS_REDIS_URL is configured to avoid reading from/writing to shared cache.

    Args:
        team: The team to get flags for

    Returns:
        List of flag dictionaries (empty list if not found or FLAGS_REDIS_URL not configured)
    """
    if not settings.FLAGS_REDIS_URL:
        return []

    result = flags_hypercache.get_from_cache(team)
    if result is None:
        return []
    return result.get("flags", [])


def update_flags_cache(team: Team) -> None:
    """
    Update the flags cache for a team.

    This explicitly updates both Redis and S3 with the latest flag data.
    Only operates when FLAGS_REDIS_URL is configured to avoid writing to shared cache.

    Args:
        team: The team to update cache for
    """
    if not settings.FLAGS_REDIS_URL:
        return

    flags_hypercache.update_cache(team)


def clear_flags_cache(team: Team, kinds: list[str] | None = None) -> None:
    """
    Clear the flags cache for a team.

    Only operates when FLAGS_REDIS_URL is configured to avoid writing to shared cache.

    Args:
        team: The team to clear cache for
        kinds: Optional list of cache kinds to clear ("redis", "s3")
    """
    if not settings.FLAGS_REDIS_URL:
        return

    flags_hypercache.clear_cache(team, kinds=kinds)


# Signal handlers for automatic cache invalidation


@receiver(post_save, sender=FeatureFlag)
@receiver(post_delete, sender=FeatureFlag)
def feature_flag_changed_flags_cache(sender, instance: "FeatureFlag", **kwargs):
    """
    Invalidate flags cache when a feature flag is created, updated, or deleted.

    This ensures the feature-flags service always has fresh flag data after any flag changes.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not settings.FLAGS_REDIS_URL:
        return

    from posthog.tasks.feature_flags import update_team_service_flags_cache

    # Defer task execution until after the transaction commits to avoid race conditions
    transaction.on_commit(lambda: update_team_service_flags_cache.delay(instance.team_id))


@receiver(post_save, sender=Team)
def team_created_flags_cache(sender, instance: "Team", created: bool, **kwargs):
    """
    Warm flags cache when a team is created.

    This ensures the cache is immediately available for new teams.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not created or not settings.FLAGS_REDIS_URL:
        return

    from posthog.tasks.feature_flags import update_team_service_flags_cache

    transaction.on_commit(lambda: update_team_service_flags_cache.delay(instance.id))


@receiver(post_delete, sender=Team)
def team_deleted_flags_cache(sender, instance: "Team", **kwargs):
    """
    Clear flags cache when a team is deleted.

    This ensures we don't have stale cache entries for deleted teams.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not settings.FLAGS_REDIS_URL:
        return

    # For unit tests, only clear Redis to avoid S3 timestamp issues with frozen time
    kinds = ["redis"] if settings.TEST else None
    clear_flags_cache(instance, kinds=kinds)
