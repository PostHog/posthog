"""Project settings helpers for themes and live events tokens."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from rest_framework.request import Request

from posthog.api.livestream_impersonation import LivestreamImpersonation
from posthog.auth import OAuthAccessTokenAuthentication, SessionAuthentication, WorkloadAccessTokenAuthentication
from posthog.helpers.impersonation import get_original_user_id_from_session
from posthog.jwt import PosthogJwtAudience, encode_jwt, signing_key_fingerprint
from posthog.models import Team, User
from posthog.models.data_color_theme import DataColorTheme
from posthog.permissions import get_authenticator_scopes
from posthog.scopes import scopes_not_covered
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


def _live_events_token_cache_key(
    team: Team, user_id: int | None, impersonation: LivestreamImpersonation | None = None
) -> str:
    """Build the cache key for the live-events JWT.

    Includes a short fingerprint of `settings.JWT_SIGNING_KEY` so that rotating the
    signing key automatically partitions the cache namespace - cached tokens signed
    with the old key become unreachable rather than served until TTL.
    Hashing also defends the cache key against future api-token formats that
    might contain the `:` separator we use between components.
    """
    signing_fingerprint = signing_key_fingerprint(settings.JWT_SIGNING_KEY)
    key = f"live_events_token:{signing_fingerprint}:{team.id}:{user_id}:{team.api_token}:{team.organization_id}"
    return f"{key}:impersonation:{impersonation.cache_key}" if impersonation is not None else key


def get_or_mint_live_events_token(
    team: Team, user_id: int | None, *, impersonation: LivestreamImpersonation | None = None
) -> str:
    """Return a cached live-events JWT for this (team, user) pair, minting one if missing.

    Ordinary JWTs are valid for 7 days. Their cache TTL is 24h, so a token returned
    from cache still has at least 6 days of remaining validity. The cache key includes
    every field that ends up in the claims so api-token rotations or organization
    moves automatically force a fresh mint, plus a JWT_SIGNING_KEY fingerprint so
    signing-key rotation auto-partitions the cache namespace (no manual flush needed).
    Impersonated tokens expire with their source credential and use a separate cache entry.
    """
    cache_key = _live_events_token_cache_key(team, user_id, impersonation)
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    claims = {
        "team_id": team.id,
        "api_token": team.api_token,
        "user_id": user_id,
        "organization_id": str(team.organization_id),
    }
    lifetime = timedelta(days=7)
    if impersonation is not None:
        claims.update(impersonation.claims())
        lifetime = timedelta(seconds=int((impersonation.expires_at - timezone.now()).total_seconds()))
    token = encode_jwt(claims, lifetime, PosthogJwtAudience.LIVESTREAM)
    safe_cache_set(cache_key, token, timeout=min(LIVE_EVENTS_TOKEN_TTL_SECONDS, int(lifetime.total_seconds())))
    return token


def _impersonation_for_request(request: Request, impersonated_by_id: int) -> LivestreamImpersonation | None:
    user_id = request.user.id
    if user_id is None:
        return None
    authenticator = getattr(request, "successful_authenticator", None)
    if isinstance(authenticator, OAuthAccessTokenAuthentication):
        return LivestreamImpersonation.from_oauth(str(authenticator.access_token.pk), user_id, impersonated_by_id)
    session_key = request.session.session_key
    if not session_key:
        return None
    impersonation = LivestreamImpersonation.from_session(session_key, user_id, impersonated_by_id)
    return impersonation if impersonation is not None and impersonation.bind_session(session_key) else None


def live_events_token_for_request(team: Team, request: Request | None) -> str | None:
    if request is None or not request.user.is_authenticated:
        return None

    # A workload token acts as the owner, and this 7-day token would outlive it.
    authenticator = getattr(request, "successful_authenticator", None)
    if isinstance(authenticator, WorkloadAccessTokenAuthentication):
        return None

    scopes = get_authenticator_scopes(authenticator)
    if scopes is not None and "*" not in scopes and scopes_not_covered(scopes, ["query:read"]):
        return None
    impersonated_by_id = None
    if isinstance(authenticator, OAuthAccessTokenAuthentication):
        impersonated_by_id = authenticator.access_token.impersonated_by_id
    elif authenticator is None or isinstance(authenticator, SessionAuthentication):
        impersonated_by_id = get_original_user_id_from_session(request)
    if impersonated_by_id is None:
        return get_or_mint_live_events_token(team, request.user.id)
    if not User.objects.filter(id=impersonated_by_id, is_active=True, is_staff=True).exists():
        return None
    impersonation = _impersonation_for_request(request, impersonated_by_id)
    if impersonation is None:
        return None
    return get_or_mint_live_events_token(team, request.user.id, impersonation=impersonation)
