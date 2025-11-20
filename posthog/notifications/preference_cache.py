"""
Notification preference caching layer.

Caches user notification preferences in Redis to avoid database hits
during the preference filter stage.
"""

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

import structlog

logger = structlog.get_logger(__name__)

# Cache TTL: None = no expiration (invalidate on updates)
PREFERENCE_CACHE_TTL = None


def get_cache_key(user_id: int, team_id: int) -> str:
    """
    Generate cache key for user preferences.

    Args:
        user_id: User ID
        team_id: Team ID

    Returns:
        Redis cache key
    """
    return f"notif_prefs:{user_id}:{team_id}"


def get_user_preferences(user_id: int, team_id: int) -> dict[str, bool]:
    """
    Get user notification preferences (cached).

    Returns a dict mapping resource_type -> enabled status.
    Default: all notification types enabled (opt-in model).

    Args:
        user_id: User ID
        team_id: Team ID

    Returns:
        Dict like {"feature_flag": True, "alert": False, ...}
    """
    cache_key = get_cache_key(user_id, team_id)
    cached = cache.get(cache_key)

    if cached is not None:
        logger.debug(
            "preference_cache_hit",
            user_id=user_id,
            team_id=team_id,
        )
        return cached

    # Cache miss - query database
    from posthog.models.notification_preference import NotificationPreference

    preferences = NotificationPreference.objects.filter(
        user_id=user_id,
        team_id=team_id,
    ).values("resource_type", "enabled")

    # Build dict from queryset
    prefs_dict = {pref["resource_type"]: pref["enabled"] for pref in preferences}

    # Cache the preferences
    cache.set(cache_key, prefs_dict, PREFERENCE_CACHE_TTL)

    logger.debug(
        "preference_cache_miss",
        user_id=user_id,
        team_id=team_id,
        cached_prefs=len(prefs_dict),
    )

    return prefs_dict


def should_notify_user(
    user_id: int,
    team_id: int,
    resource_type: str,
) -> bool:
    """
    Check if user should receive notification for resource type.

    Default: True (opt-in model - users receive all by default).

    Args:
        user_id: User ID
        team_id: Team ID
        resource_type: Notification resource type

    Returns:
        True if user should be notified
    """
    prefs = get_user_preferences(user_id, team_id)

    # If no explicit preference, default to enabled
    return prefs.get(resource_type, True)


def invalidate_user_preferences(user_id: int, team_id: int) -> None:
    """
    Invalidate cached preferences for a user.

    Called automatically via Django signals when preferences change.

    Args:
        user_id: User ID
        team_id: Team ID
    """
    cache_key = get_cache_key(user_id, team_id)
    cache.delete(cache_key)

    logger.info(
        "preference_cache_invalidated",
        user_id=user_id,
        team_id=team_id,
    )


# Django signals for automatic cache invalidation


@receiver(post_save, sender="posthog.NotificationPreference")
def invalidate_on_preference_save(sender, instance, **kwargs):
    """Invalidate cache when preference is saved."""
    invalidate_user_preferences(instance.user_id, instance.team_id)


@receiver(post_delete, sender="posthog.NotificationPreference")
def invalidate_on_preference_delete(sender, instance, **kwargs):
    """Invalidate cache when preference is deleted."""
    invalidate_user_preferences(instance.user_id, instance.team_id)
