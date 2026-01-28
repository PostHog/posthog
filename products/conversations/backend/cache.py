"""
Redis caching for Conversations widget polling endpoints.

Caches responses to reduce database load from frequent polling.
Short TTLs ensure stale data expires quickly without explicit invalidation.
"""

from django.core.cache import cache

import structlog

logger = structlog.get_logger(__name__)

# Cache TTLs (seconds)
MESSAGES_CACHE_TTL = 15  # Short TTL - messages need to appear quickly
TICKETS_CACHE_TTL = 30  # Slightly longer - ticket list changes less frequently
UNREAD_COUNT_CACHE_TTL = 30  # For dashboard polling - invalidated on changes


def _make_cache_key(prefix: str, *args: str) -> str:
    """Create a namespaced cache key."""
    key_parts = ":".join(str(arg) for arg in args)
    return f"conversations:{prefix}:{key_parts}"


# Widget Messages Cache
# Caches both initial load (after=None) and polling (after=timestamp).
# When polling, 'after' stays constant until a new message arrives,
# so cache hits are common. Stale data expires via short TTL.


def get_messages_cache_key(team_id: int, ticket_id: str, after: str | None = None) -> str:
    """Cache key for widget messages endpoint."""
    return _make_cache_key("messages", str(team_id), ticket_id, after or "initial")


def get_cached_messages(team_id: int, ticket_id: str, after: str | None = None) -> dict | None:
    """Get cached messages response."""
    key = get_messages_cache_key(team_id, ticket_id, after)
    try:
        return cache.get(key)
    except Exception:
        logger.warning("conversations_cache_get_error", key=key)
        return None


def set_cached_messages(team_id: int, ticket_id: str, response_data: dict, after: str | None = None) -> None:
    """Cache messages response."""
    key = get_messages_cache_key(team_id, ticket_id, after)
    try:
        cache.set(key, response_data, timeout=MESSAGES_CACHE_TTL)
    except Exception:
        logger.warning("conversations_cache_set_error", key=key)


# Widget Tickets List Cache


def get_tickets_cache_key(team_id: int, widget_session_id: str, status: str | None = None) -> str:
    """Cache key for widget tickets list endpoint."""
    return _make_cache_key("tickets", str(team_id), widget_session_id, status or "all")


def get_cached_tickets(team_id: int, widget_session_id: str, status: str | None = None) -> dict | None:
    """Get cached tickets list response."""
    key = get_tickets_cache_key(team_id, widget_session_id, status)
    try:
        return cache.get(key)
    except Exception:
        logger.warning("conversations_cache_get_error", key=key)
        return None


def set_cached_tickets(team_id: int, widget_session_id: str, response_data: dict, status: str | None = None) -> None:
    """Cache tickets list response."""
    key = get_tickets_cache_key(team_id, widget_session_id, status)
    try:
        cache.set(key, response_data, timeout=TICKETS_CACHE_TTL)
    except Exception:
        logger.warning("conversations_cache_set_error", key=key)


# Unread Count Cache (for dashboard nav badge)
# Caches the total unread ticket count for a team.
# Invalidated when: customer sends message, ticket resolved, ticket marked as read.


def get_unread_count_cache_key(team_id: int) -> str:
    """Cache key for unread ticket count endpoint."""
    return _make_cache_key("unread_count", str(team_id))


def get_cached_unread_count(team_id: int) -> int | None:
    """Get cached unread count."""
    key = get_unread_count_cache_key(team_id)
    try:
        return cache.get(key)
    except Exception:
        logger.warning("conversations_cache_get_error", key=key)
        return None


def set_cached_unread_count(team_id: int, count: int) -> None:
    """Cache unread count."""
    key = get_unread_count_cache_key(team_id)
    try:
        cache.set(key, count, timeout=UNREAD_COUNT_CACHE_TTL)
    except Exception:
        logger.warning("conversations_cache_set_error", key=key)


def invalidate_unread_count_cache(team_id: int) -> None:
    """Invalidate unread count cache for a team."""
    key = get_unread_count_cache_key(team_id)
    try:
        cache.delete(key)
    except Exception:
        logger.warning("conversations_cache_delete_error", key=key)
