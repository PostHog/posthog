"""
Redis caching for Conversations widget polling endpoints.

Caches responses to reduce database load from frequent polling.
Invalidated automatically when messages are created or tickets updated.
"""

from django.core.cache import cache

import structlog

logger = structlog.get_logger(__name__)

# Cache TTLs (seconds)
MESSAGES_CACHE_TTL = 15  # Short TTL - messages need to appear quickly
TICKETS_CACHE_TTL = 30  # Slightly longer - ticket list changes less frequently


def _make_cache_key(prefix: str, *args: str) -> str:
    """Create a namespaced cache key."""
    key_parts = ":".join(str(arg) for arg in args)
    return f"conversations:{prefix}:{key_parts}"


# Widget Messages Cache
# Caches both initial load (after=None) and polling (after=timestamp).
# When polling, 'after' stays constant until a new message arrives,
# so cache hits are common. When a new message arrives, cache is invalidated via signal.


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


def invalidate_messages_cache(team_id: int, ticket_id: str) -> None:
    """Invalidate all messages cache for a ticket (all 'after' variations)."""
    pattern = _make_cache_key("messages", str(team_id), ticket_id, "*")
    try:
        if hasattr(cache, "delete_pattern"):
            cache.delete_pattern(pattern)
        else:
            # Fallback: delete initial key. Other variations expire via TTL.
            cache.delete(get_messages_cache_key(team_id, ticket_id, None))
    except Exception:
        logger.warning("conversations_cache_invalidate_error", pattern=pattern, exc_info=True)


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


def invalidate_tickets_cache(team_id: int, widget_session_id: str) -> None:
    """Invalidate all tickets cache for a widget session.
    Note: With fallback (no delete_pattern), status-filtered caches may serve stale
    data for up to TICKETS_CACHE_TTL seconds. This is acceptable given the short TTL.
    """
    pattern = _make_cache_key("tickets", str(team_id), widget_session_id, "*")
    try:
        if hasattr(cache, "delete_pattern"):
            cache.delete_pattern(pattern)
        else:
            # Fallback: delete the "all" key. Status-filtered variations will expire via TTL.
            cache.delete(get_tickets_cache_key(team_id, widget_session_id, None))
            logger.info("conversations_cache_pattern_delete_unavailable", pattern=pattern)
    except Exception:
        logger.warning("conversations_cache_invalidate_error", pattern=pattern, exc_info=True)
