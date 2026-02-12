"""
Toolbar OAuth backend primitives.

Non-obvious behavior documented here:
- We keep one OAuth app per organization (not global, not per team).
- We allow multiple callback redirect URIs on that app so one org can launch
  toolbar auth from multiple PostHog deployments/environments.
- OAuth state is both signed and one-time-use (cache-backed) to prevent replay.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

from django.conf import settings
from django.core import signing
from django.core.cache import cache

import requests

from posthog.api.utils import unparsed_hostname_in_allowed_url_list
from posthog.models import Team, User
from posthog.models.oauth import OAuthApplication, is_loopback_host

STATE_SIGNER_SALT = "toolbar-oauth-state-v1"
STATE_VERSION = 1
STATE_CACHE_PREFIX = "toolbar_oauth_state"
STATE_USED_CACHE_PREFIX = "toolbar_oauth_state_used"
CALLBACK_PATH = "/toolbar_oauth/callback"


class ToolbarOAuthError(Exception):
    def __init__(self, code: str, detail: str, status_code: int = 400) -> None:
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass
class ToolbarOAuthState:
    nonce: str
    user_id: int
    team_id: int
    app_url: str
    action_id: int | None = None
    experiment_id: int | str | None = None
    product_tour_id: str | None = None
    user_intent: str | None = None


def _cache_key(prefix: str, nonce: str) -> str:
    return f"{prefix}:{nonce}"


def _split_redirect_uris(redirect_uris: str) -> list[str]:
    """Split space-delimited redirect URIs, dropping empty entries."""
    return [uri for uri in redirect_uris.split(" ") if uri]


def normalize_base_url_for_oauth(base_url: str) -> str:
    """
    OAuth redirect URI validation requires HTTPS for non-loopback hosts.
    If request context is HTTP on a non-loopback host (e.g. Django testserver),
    upgrade the scheme to HTTPS for OAuth URL construction.
    """
    parsed = urlparse(base_url)
    if parsed.scheme == "http" and not is_loopback_host(parsed.hostname):
        parsed = parsed._replace(scheme="https")
        return urlunparse(parsed).rstrip("/")
    return base_url.rstrip("/")


def normalize_and_validate_app_url(team: Team, app_url: str) -> str:
    try:
        parsed = urlparse(app_url)
    except ValueError as exc:
        raise ToolbarOAuthError("invalid_app_url", "Invalid app_url", 400) from exc

    if not parsed.scheme or not parsed.hostname:
        raise ToolbarOAuthError("invalid_app_url", "app_url must include scheme and host", 400)

    if not team or not unparsed_hostname_in_allowed_url_list(team.app_urls, app_url):
        raise ToolbarOAuthError("forbidden_app_url", "Can only redirect to a permitted domain.", 403)

    # preserve path/query/fragment
    return app_url


def get_or_create_toolbar_oauth_application(base_url: str, user: User) -> OAuthApplication:
    """
    Return the toolbar OAuth app for the user's organization.

    The app is org-scoped so organizations do not share client IDs.
    Redirect URIs are appended (not replaced) so an org can authorize toolbar
    from multiple hosts.
    """
    base_url = normalize_base_url_for_oauth(base_url)
    redirect_uri = f"{base_url.rstrip('/')}{CALLBACK_PATH}"
    app_name = settings.TOOLBAR_OAUTH_APPLICATION_NAME

    existing = OAuthApplication.objects.filter(
        organization=user.organization,
        name=app_name,
        client_type=OAuthApplication.CLIENT_PUBLIC,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
    ).first()

    if existing:
        # Keep redirect URIs in sync for this organization deployment URLs.
        existing_redirect_uris = _split_redirect_uris(existing.redirect_uris)
        if redirect_uri not in existing_redirect_uris:
            # DOT stores redirect URIs as a single space-delimited string.
            # We append instead of replacing so one org can authorize toolbar
            # from multiple PostHog hosts (e.g. US/EU or prod/staging).
            existing.redirect_uris = " ".join([*existing_redirect_uris, redirect_uri])
            existing.save(update_fields=["redirect_uris"])
        return existing

    # NOTE: Keep as non-first-party for now to avoid potential security issues.
    return OAuthApplication.objects.create(
        name=app_name,
        user=user,
        organization=user.organization,
        client_type=OAuthApplication.CLIENT_PUBLIC,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris=redirect_uri,
        algorithm="RS256",
        skip_authorization=False,
        is_first_party=False,
    )


def build_toolbar_oauth_state(state: ToolbarOAuthState) -> tuple[str, datetime]:
    """
    Build a signed state envelope and mark its nonce as pending in cache.

    Signature protects integrity of the embedded context. The cache marker lets
    us enforce one-time-use later during exchange.
    """
    nonce = state.nonce
    now = datetime.now(UTC)
    expires_at = now.timestamp() + settings.TOOLBAR_OAUTH_STATE_TTL_SECONDS

    payload: dict[str, Any] = {
        "v": STATE_VERSION,
        "nonce": nonce,
        "user_id": state.user_id,
        "team_id": state.team_id,
        "app_url": state.app_url,
        "action_id": state.action_id,
        "experiment_id": state.experiment_id,
        "product_tour_id": state.product_tour_id,
        "user_intent": state.user_intent,
        "iat": int(now.timestamp()),
    }

    signed_state = signing.dumps(payload, salt=STATE_SIGNER_SALT)
    cache.set(
        _cache_key(STATE_CACHE_PREFIX, nonce), {"pending": True}, timeout=settings.TOOLBAR_OAUTH_STATE_TTL_SECONDS
    )

    return signed_state, datetime.fromtimestamp(expires_at, tz=UTC)


def validate_and_consume_toolbar_oauth_state(
    signed_state: str,
    request_user: User,
    request_team: Team,
) -> dict[str, Any]:
    """
    Verify state integrity and consume nonce to prevent replay.

    This enforces:
    - signature/expiry checks
    - nonce existence and one-time use
    - state binding to current user/team/app_url
    """
    try:
        payload = signing.loads(signed_state, salt=STATE_SIGNER_SALT, max_age=settings.TOOLBAR_OAUTH_STATE_TTL_SECONDS)
    except signing.SignatureExpired as exc:
        raise ToolbarOAuthError("invalid_state", "OAuth state has expired", 400) from exc
    except signing.BadSignature as exc:
        raise ToolbarOAuthError("invalid_state", "OAuth state is invalid", 400) from exc

    if payload.get("v") != STATE_VERSION:
        raise ToolbarOAuthError("invalid_state", "Invalid OAuth state version", 400)

    nonce = payload.get("nonce")
    if not nonce:
        raise ToolbarOAuthError("invalid_state", "OAuth state is missing nonce", 400)

    pending_key = _cache_key(STATE_CACHE_PREFIX, nonce)
    used_key = _cache_key(STATE_USED_CACHE_PREFIX, nonce)

    # replay guard
    if cache.get(used_key):
        raise ToolbarOAuthError("state_replay", "OAuth state has already been used", 400)

    pending = cache.get(pending_key)
    if not pending:
        raise ToolbarOAuthError("state_not_found", "OAuth state was not found or expired", 400)

    # best-effort one-time use marker
    # `cache.add` is atomic: only one concurrent request can claim a nonce.
    # This closes the race where two exchanges arrive before `pending_key` is deleted.
    added = cache.add(used_key, True, timeout=settings.TOOLBAR_OAUTH_STATE_TTL_SECONDS)
    if not added:
        raise ToolbarOAuthError("state_replay", "OAuth state has already been used", 400)
    cache.delete(pending_key)

    # TODO: Is pk valid in this context?
    if payload.get("user_id") != request_user.pk:
        raise ToolbarOAuthError("state_user_mismatch", "OAuth state project mismatch", 400)

    if payload.get("team_id") != request_team.pk:
        raise ToolbarOAuthError("state_team_mismatch", "OAuth state team mismatch", 400)

    normalize_and_validate_app_url(request_team, payload.get("app_url"))
    return payload


def build_authorization_url(
    base_url: str,
    application: OAuthApplication,
    state: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
) -> str:
    base_url = normalize_base_url_for_oauth(base_url)
    if code_challenge_method != "S256":
        raise ToolbarOAuthError("invalid_code_challenge_method", "Unsupported code challenge method", 400)

    redirect_uri = f"{base_url.rstrip('/')}{CALLBACK_PATH}"
    scopes = " ".join(settings.TOOLBAR_OAUTH_SCOPES)

    params = {
        "client_id": application.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "scope": scopes,
    }

    return f"{base_url.rstrip('/')}/oauth/authorize/?{urlencode(params)}"


def exchange_code_for_tokens(
    base_url: str,
    client_id: str,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    base_url = normalize_base_url_for_oauth(base_url)
    redirect_uri = f"{base_url.rstrip('/')}{CALLBACK_PATH}"
    token_url = f"{base_url.rstrip('/')}/oauth/token/"

    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }

    try:
        response = requests.post(token_url, data=data, timeout=settings.TOOLBAR_OAUTH_EXCHANGE_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise ToolbarOAuthError("token_exchange_unavailable", "Failed to exchange code for tokens", 500) from exc

    payload = response.json() if response.content else {}

    if response.status_code >= 400:
        error = payload.get("error", "token_exchange_failed")
        detail = payload.get("error_description", "OAuth token exchange failed")
        raise ToolbarOAuthError(error, detail, 400)

    return {
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "expires_in": payload.get("expires_in"),
        "token_type": payload.get("token_type"),
        "scope": payload.get("scope"),
    }


def new_state_nonce() -> str:
    return secrets.token_urlsafe(24)
