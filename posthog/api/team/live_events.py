"""Project settings helpers for themes and live events tokens."""

from datetime import timedelta

from django.conf import settings

from posthog.jwt import PosthogJwtAudience, encode_jwt, signing_key_fingerprint
from posthog.models import Team
from posthog.models.data_color_theme import DataColorTheme
from posthog.utils import get_safe_cache, safe_cache_set

_default_theme_id_cache: int | None = None
LIVE_EVENTS_TOKEN_TTL_SECONDS = 24 * 60 * 60


def _default_data_color_theme_id() -> int | None:
    """Return the system-wide default DataColorTheme id, cached for process lifetime.

    The default is created by data migration `0537_data_color_themes.py` and
    is effectively a constant after deploy - cache it to skip a per-render PG
    round-trip in `TeamSerializer.to_representation` for orgs without the
    DATA_COLOR_THEMES feature.

    We deliberately do NOT cache `None`: if the first call lands before the
    migration is applied, or against an instance where no global default
    exists yet, we want subsequent calls to recover automatically once the
    row appears. `.order_by("id")` keeps the chosen ID deterministic across
    workers if multiple globals ever exist.
    """
    global _default_theme_id_cache
    if _default_theme_id_cache is None:
        _default_theme_id_cache = (
            DataColorTheme.objects.filter(team_id__isnull=True).order_by("id").values_list("id", flat=True).first()
        )
    return _default_theme_id_cache


def _reset_default_data_color_theme_id_cache() -> None:
    """Test-only helper for explicit cache invalidation."""
    global _default_theme_id_cache
    _default_theme_id_cache = None


def _live_events_token_cache_key(team: Team, user_id: int | None) -> str:
    """Build the cache key for the live-events JWT.

    Includes a short fingerprint of `settings.JWT_SIGNING_KEY` so that rotating the
    signing key automatically partitions the cache namespace - cached tokens signed
    with the old key become unreachable rather than served until TTL.
    Hashing also defends the cache key against future api-token formats that
    might contain the `:` separator we use between components.
    """
    signing_fingerprint = signing_key_fingerprint(settings.JWT_SIGNING_KEY)
    return f"live_events_token:{signing_fingerprint}:{team.id}:{user_id}:{team.api_token}:{team.organization_id}"


def get_or_mint_live_events_token(team: Team, user_id: int | None) -> str:
    """Return a cached live-events JWT for this (team, user) pair, minting one if missing.

    The JWT itself is valid for 7 days. The cache TTL is 24h, so any token returned
    from cache still has at least 6 days of remaining validity. The cache key includes
    every field that ends up in the claims so api-token rotations or organization
    moves automatically force a fresh mint, plus a JWT_SIGNING_KEY fingerprint so
    signing-key rotation auto-partitions the cache namespace (no manual flush needed).
    """
    cache_key = _live_events_token_cache_key(team, user_id)
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    claims = {
        "team_id": team.id,
        "api_token": team.api_token,
        "user_id": user_id,
        "organization_id": str(team.organization_id),
    }
    token = encode_jwt(claims, timedelta(days=7), PosthogJwtAudience.LIVESTREAM)
    safe_cache_set(cache_key, token, timeout=LIVE_EVENTS_TOKEN_TTL_SECONDS)
    return token
