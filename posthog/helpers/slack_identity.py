"""Slack identity resolution shared by anything that mirrors comment threads to/from Slack.

Token-agnostic: every function takes a ``slack_sdk.WebClient`` so the caller supplies the
workspace's bot token (the conversations SupportHog bot, the generic Slack ``Integration``,
etc.). Profile and avatar lookups are cached in Redis. Slack user ids are only guaranteed
unique per workspace, so profile cache keys are namespaced by the required ``workspace``
(the Slack team id); email keys are globally unique already.
"""

from types import MappingProxyType

from django.core.cache import cache

import structlog
from slack_sdk import WebClient

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

logger = structlog.get_logger(__name__)

# Short TTLs keep cached Slack profiles/avatars reasonably fresh.
SLACK_USER_CACHE_TTL = 5 * 60  # 5 minutes
SLACK_AVATAR_CACHE_TTL = 5 * 60  # 5 minutes

_UNKNOWN_USER = MappingProxyType({"name": "Unknown", "email": None, "avatar": None})


def _make_cache_key(prefix: str, *args: str) -> str:
    """Create a namespaced cache key."""
    key_parts = ":".join(str(arg) for arg in args)
    return f"slack_identity:{prefix}:{key_parts}"


def get_cached_slack_user(slack_user_id: str, workspace: str) -> dict | None:
    """Get cached Slack user profile."""
    key = _make_cache_key("slack_user", workspace, slack_user_id)
    try:
        return cache.get(key)
    except Exception:
        logger.warning("slack_identity_cache_get_error", key=key)
        return None


def set_cached_slack_user(slack_user_id: str, user_info: dict, workspace: str) -> None:
    """Cache a Slack user profile."""
    key = _make_cache_key("slack_user", workspace, slack_user_id)
    try:
        cache.set(key, user_info, timeout=SLACK_USER_CACHE_TTL)
    except Exception:
        logger.warning("slack_identity_cache_set_error", key=key)


def get_cached_slack_avatar(email: str) -> str | None:
    """Get cached Slack avatar URL for an email. Returns None on cache miss, empty string for negative cache."""
    key = _make_cache_key("slack_avatar", email.lower())
    try:
        return cache.get(key)
    except Exception:
        logger.warning("slack_identity_cache_get_error", key=key)
        return None


def set_cached_slack_avatar(email: str, avatar_url: str) -> None:
    """Cache a Slack avatar URL (or empty string for negative cache)."""
    key = _make_cache_key("slack_avatar", email.lower())
    try:
        cache.set(key, avatar_url, timeout=SLACK_AVATAR_CACHE_TTL)
    except Exception:
        logger.warning("slack_identity_cache_set_error", key=key)


def resolve_slack_user(client: WebClient, slack_user_id: str, *, workspace: str) -> dict:
    """Resolve a Slack user ID to name, email, and avatar. Cached in Redis for 5 minutes.

    Slack user ids are only unique per workspace, so ``workspace`` (the Slack team id the
    event or integration is scoped to) namespaces the cache — a colliding id from another
    workspace can't be served from this one's cache.
    """
    if not slack_user_id:
        logger.warning("slack_user_resolve_empty_id")
        return dict(_UNKNOWN_USER)

    cached = get_cached_slack_user(slack_user_id, workspace)
    if cached is not None:
        return cached

    try:
        response = client.users_info(user=slack_user_id)
        raw_data = response.data if hasattr(response, "data") else None
        data: dict = raw_data if isinstance(raw_data, dict) else {}

        if not data.get("ok"):
            logger.warning(
                "slack_user_resolve_not_ok",
                slack_user_id=slack_user_id,
                error=data.get("error"),
            )
            return dict(_UNKNOWN_USER)

        user_data = data.get("user") or {}
        profile = user_data.get("profile") or {}
        name = profile.get("display_name") or profile.get("real_name") or "Unknown"
        result = {
            "name": name,
            "email": profile.get("email"),
            "avatar": profile.get("image_72"),
        }
        set_cached_slack_user(slack_user_id, result, workspace)
        return result
    except Exception as e:
        logger.warning("slack_user_resolve_failed", slack_user_id=slack_user_id, error=str(e))
        return dict(_UNKNOWN_USER)


def resolve_slack_avatar_by_email(client: WebClient, email: str) -> str | None:
    """Look up a Slack user by email and return their profile image URL. Cached in Redis."""
    if not email:
        return None

    cached = get_cached_slack_avatar(email)
    if cached is not None:
        return cached or None  # empty string = negative cache

    try:
        response = client.users_lookupByEmail(email=email)
        raw_data = response.data if hasattr(response, "data") else None
        data: dict = raw_data if isinstance(raw_data, dict) else {}

        if not data.get("ok"):
            set_cached_slack_avatar(email, "")
            return None

        profile = (data.get("user") or {}).get("profile") or {}
        avatar = profile.get("image_72") or ""
        set_cached_slack_avatar(email, avatar)
        return avatar or None
    except Exception:
        # Don't negative-cache on transient errors (rate limits, network)
        # so the next reply retries the lookup.
        logger.warning("slack_avatar_lookup_failed", email=email)
        return None


def resolve_posthog_user_for_slack(email: str | None, team: Team) -> User | None:
    """Match a Slack user's email to a PostHog user within the team's organization."""
    if not email:
        return None
    membership = (
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
            user__email=email,
        )
        .select_related("user")
        .first()
    )
    return membership.user if membership else None
