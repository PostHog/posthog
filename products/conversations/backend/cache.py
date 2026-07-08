"""
Redis caching for Conversations widget polling endpoints.

Caches responses to reduce database load from frequent polling.
Short TTLs ensure stale data expires quickly without explicit invalidation.
"""

import json
import hashlib
from collections.abc import Generator
from contextlib import contextmanager

from django.core.cache import cache

import structlog

from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.personhog_client.caller_tag import personhog_caller_tag

from products.conversations.backend.models.constants import Status

logger = structlog.get_logger(__name__)

# Cache TTLs (seconds)
MESSAGES_CACHE_TTL = 15  # Short TTL - messages need to appear quickly
TICKETS_CACHE_TTL = 30  # Slightly longer - ticket list changes less frequently
UNREAD_COUNT_CACHE_TTL = 30  # For dashboard polling - invalidated on changes
SLACK_AVATAR_CACHE_TTL = 5 * 60  # 5 minutes for slack avatar lookup

# All possible status filter values for tickets cache invalidation
_TICKETS_STATUS_VARIANTS: list[str | None] = [None, *[s.value for s in Status]]


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


def invalidate_messages_cache(team_id: int, ticket_id: str) -> None:
    """Invalidate the initial-load messages cache entry for a ticket (after=None). Polling entries (after=<ts>) expire via TTL."""
    key = get_messages_cache_key(team_id, ticket_id, None)
    try:
        cache.delete(key)
    except Exception:
        logger.warning("conversations_cache_delete_error", key=key)


def invalidate_tickets_cache(team_id: int, widget_session_id: str) -> None:
    """Delete all status-filtered ticket cache variants for a widget session."""
    keys = [get_tickets_cache_key(team_id, widget_session_id, s) for s in _TICKETS_STATUS_VARIANTS]
    try:
        cache.delete_many(keys)
    except Exception:
        logger.warning("conversations_cache_invalidate_error", keys=keys)


# Slack User Cache
# Caches Slack user profile lookups (name, email, avatar) to reduce
# Slack API calls. Keyed by slack_user_id — IDs are functionally unique
# across workspaces. Short TTL keeps profiles reasonably fresh.

SLACK_USER_CACHE_TTL = 5 * 60  # 5 minutes


def get_cached_slack_user(slack_user_id: str) -> dict | None:
    """Get cached Slack user profile."""
    key = _make_cache_key("slack_user", slack_user_id)
    try:
        return cache.get(key)
    except Exception:
        logger.warning("conversations_cache_get_error", key=key)
        return None


PERSON_DISTINCT_IDS_CACHE_TTL = 30  # seconds


def get_person_distinct_ids(team_id: int, distinct_id: str) -> list[str]:
    """Resolve all distinct_ids linked to a person.

    Returns all distinct_ids for the person, or a single-element list with
    the input distinct_id if no person is found. Cached briefly to avoid
    hitting the DB on every widget poll.
    """

    key = _make_cache_key("person_dids", str(team_id), distinct_id)
    try:
        cached = cache.get(key)
        if cached is not None:
            return cached
    except Exception:
        logger.warning("conversations_cache_get_error", key=key)

    with personhog_caller_tag("conversations/widget-person-distinct-ids"):
        persons = get_persons_by_distinct_ids(team_id, [distinct_id])
    all_ids = persons[0].distinct_ids if persons and persons[0].distinct_ids else [distinct_id]

    try:
        cache.set(key, all_ids, timeout=PERSON_DISTINCT_IDS_CACHE_TTL)
    except Exception:
        logger.warning("conversations_cache_set_error", key=key)

    return all_ids


def set_cached_slack_user(slack_user_id: str, user_info: dict) -> None:
    """Cache a Slack user profile."""
    key = _make_cache_key("slack_user", slack_user_id)
    try:
        cache.set(key, user_info, timeout=SLACK_USER_CACHE_TTL)
    except Exception:
        logger.warning("conversations_cache_set_error", key=key)


# Slack Avatar-by-Email Cache
# Caches the result of users.lookupByEmail so outbound replies can show
# the replying user's Slack profile picture. Empty string = negative cache
# (user not found in the Slack workspace for that email).


def get_cached_slack_avatar(email: str) -> str | None:
    """Get cached Slack avatar URL for an email. Returns None on cache miss, empty string for negative cache."""
    key = _make_cache_key("slack_avatar", email.lower())
    try:
        return cache.get(key)
    except Exception:
        logger.warning("conversations_cache_get_error", key=key)
        return None


def set_cached_slack_avatar(email: str, avatar_url: str) -> None:
    """Cache a Slack avatar URL (or empty string for negative cache)."""
    key = _make_cache_key("slack_avatar", email.lower())
    try:
        cache.set(key, avatar_url, timeout=SLACK_AVATAR_CACHE_TTL)
    except Exception:
        logger.warning("conversations_cache_set_error", key=key)


# Slack Bot User ID Cache
# Caches the bot's own user_id (from auth.test) so member join/leave handlers
# don't burn Slack's Tier-1 rate-limit budget with a round-trip per event.
# Keyed by team_id; the identity is stable per bot token. Only positive results
# are cached so a transient auth.test failure retries on the next event.

BOT_USER_ID_CACHE_TTL = 60 * 60  # 1 hour


def get_cached_bot_user_id(team_id: int) -> str | None:
    """Get the cached Slack bot user_id for a team."""
    key = _make_cache_key("slack_bot_user_id", str(team_id))
    try:
        return cache.get(key)
    except Exception:
        logger.warning("conversations_cache_get_error", key=key)
        return None


def set_cached_bot_user_id(team_id: int, bot_user_id: str) -> None:
    """Cache the Slack bot user_id for a team."""
    key = _make_cache_key("slack_bot_user_id", str(team_id))
    try:
        cache.set(key, bot_user_id, timeout=BOT_USER_ID_CACHE_TTL)
    except Exception:
        logger.warning("conversations_cache_set_error", key=key)


# Slack Nudge Suppression
# Suppresses the opt-in "open a ticket?" nudge so we don't pester a user on every
# message in a channel. Set after sending a nudge (short cooldown) or after the user
# clicks "No thanks" (longer). Keyed by team:channel:user — presence means suppressed.

NUDGE_COOLDOWN_TTL = 5 * 60  # after nudging the same user in a channel
NUDGE_DISMISS_TTL = 3 * 60 * 60  # after the user clicks "No thanks"


def _nudge_suppress_key(team_id: int, channel: str, slack_user_id: str) -> str:
    return _make_cache_key("slack_nudge_suppressed", str(team_id), channel, slack_user_id)


def is_nudge_suppressed(team_id: int, channel: str, slack_user_id: str) -> bool:
    """Whether the confirm-ticket nudge is currently suppressed for this user in this channel."""
    key = _nudge_suppress_key(team_id, channel, slack_user_id)
    try:
        return cache.get(key) is not None
    except Exception:
        logger.warning("conversations_cache_get_error", key=key)
        return False


def suppress_nudge(team_id: int, channel: str, slack_user_id: str, ttl_seconds: int) -> None:
    """Suppress the nudge for this user in this channel for ttl_seconds."""
    key = _nudge_suppress_key(team_id, channel, slack_user_id)
    try:
        cache.set(key, True, timeout=ttl_seconds)
    except Exception:
        logger.warning("conversations_cache_set_error", key=key)


# Teams User Cache
# Caches Teams user profile lookups (displayName, email) resolved via Graph API.
# Keyed by tenant_id:teams_user_id. Short TTL keeps profiles fresh.

TEAMS_USER_CACHE_TTL = 5 * 60  # 5 minutes


def get_cached_teams_user(tenant_id: str, teams_user_id: str) -> dict | None:
    key = _make_cache_key("teams_user", tenant_id, teams_user_id)
    try:
        return cache.get(key)
    except Exception:
        logger.warning("conversations_cache_get_error", key=key)
        return None


def set_cached_teams_user(tenant_id: str, teams_user_id: str, user_info: dict) -> None:
    key = _make_cache_key("teams_user", tenant_id, teams_user_id)
    try:
        cache.set(key, user_info, timeout=TEAMS_USER_CACHE_TTL)
    except Exception:
        logger.warning("conversations_cache_set_error", key=key)


# Resolved Groups Cache
# Caches the ClickHouse-resolved $groups for a customer (see events._resolve_groups_from_analytics).
# Ticket conversations re-resolve groups on creation plus every customer message, so this bounds
# the ClickHouse fallback to one query per customer per TTL. Empty dict = negative cache
# (customer's events carry no organization group). Org membership churn is slow, hence long TTLs.

RESOLVED_GROUPS_CACHE_TTL = 12 * 60 * 60  # 12 hours
RESOLVED_GROUPS_NEGATIVE_CACHE_TTL = 60 * 60  # 1 hour


# Slack Ticket Creation Lock
# Serializes concurrent ticket creation for the same Slack thread so two reaction_added
# events from different users can't both pass the existence checks and create duplicate
# tickets. cache.add is atomic (Redis SETNX): only one worker acquires. Short TTL is a
# safety net so a crashed worker can't wedge a thread permanently.

SLACK_TICKET_CREATE_LOCK_TTL = 30  # seconds


@contextmanager
def slack_ticket_create_lock(team_id: int, channel: str, thread_ts: str) -> Generator[bool]:
    """Atomic Redis lock to serialize ticket creation for a Slack thread.

    Yields True if the lock was acquired, False if another worker holds it.
    Releases the lock on exit when acquired.
    """
    key = _make_cache_key("slack_ticket_create_lock", str(team_id), channel, thread_ts)
    acquired = cache.add(key, True, timeout=SLACK_TICKET_CREATE_LOCK_TTL)
    try:
        yield acquired
    finally:
        if acquired:
            cache.delete(key)


def _resolved_groups_cache_key(team_id: int, distinct_ids: list[str]) -> str:
    # JSON-encode for an unambiguous preimage: joining with a separator collides
    # when distinct_ids themselves contain it (["a|b", "c"] vs ["a", "b|c"]).
    digest = hashlib.sha256(json.dumps(sorted(distinct_ids)).encode()).hexdigest()[:32]
    return _make_cache_key("resolved_groups", str(team_id), digest)


def get_cached_resolved_groups(team_id: int, distinct_ids: list[str]) -> dict | None:
    """Get cached resolved groups. Returns None on cache miss, {} for negative cache."""
    key = _resolved_groups_cache_key(team_id, distinct_ids)
    try:
        return cache.get(key)
    except Exception:
        logger.warning("conversations_cache_get_error", key=key)
        return None


def set_cached_resolved_groups(team_id: int, distinct_ids: list[str], groups: dict | None) -> None:
    """Cache resolved groups (or {} as negative cache when resolution found nothing)."""
    key = _resolved_groups_cache_key(team_id, distinct_ids)
    timeout = RESOLVED_GROUPS_CACHE_TTL if groups else RESOLVED_GROUPS_NEGATIVE_CACHE_TTL
    try:
        cache.set(key, groups or {}, timeout=timeout)
    except Exception:
        logger.warning("conversations_cache_set_error", key=key)
