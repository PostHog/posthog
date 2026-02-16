"""
Toolbar OAuth backend primitives.

Non-obvious behavior documented here:
- We keep one OAuth app per organization (not global, not per team).
- The redirect URI is derived from settings.SITE_URL (one per deployment).
- OAuth state is both signed and one-time-use (cache-backed) to prevent replay.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import transaction

import requests

from posthog.api.utils import unparsed_hostname_in_allowed_url_list
from posthog.models import Team, User
from posthog.models.oauth import OAuthApplication, is_loopback_host
from posthog.models.organization import Organization

STATE_SIGNER_SALT = "toolbar-oauth-state-v1"
STATE_VERSION = 1
CALLBACK_PATH = "/toolbar_oauth/callback"


def _get_redirect_uri() -> str:
    return f"{settings.SITE_URL}{CALLBACK_PATH}"


class ToolbarOAuthStateCache:
    """
    One-time-use state nonces for toolbar OAuth.
    Mark a nonce as pending when building the auth URL; claim it during token exchange.
    """

    def __init__(self) -> None:
        self._timeout = settings.TOOLBAR_OAUTH_STATE_TTL_SECONDS
        self._pending_prefix = "toolbar_oauth_state"
        self._used_prefix = "toolbar_oauth_state_used"

    def _key(self, prefix: str, nonce: str) -> str:
        return f"{prefix}:{nonce}"

    def mark_pending(self, nonce: str) -> None:
        cache.set(self._key(self._pending_prefix, nonce), True, timeout=self._timeout)

    def claim_or_raise(self, nonce: str) -> None:
        """
        Claim the nonce for one-time use.
        Raises ToolbarOAuthError if already used (replay) or not found/expired.
        """
        used_key = self._key(self._used_prefix, nonce)
        pending_key = self._key(self._pending_prefix, nonce)
        if cache.get(used_key):
            raise ToolbarOAuthError("state_replay", "OAuth state has already been used", 400)
        if not cache.get(pending_key):
            raise ToolbarOAuthError("state_not_found", "OAuth state was not found or expired", 400)
        # cache.add is atomic: only one concurrent request can claim this nonce
        if not cache.add(used_key, True, timeout=self._timeout):
            raise ToolbarOAuthError("state_replay", "OAuth state has already been used", 400)
        cache.delete(pending_key)


toolbar_oauth_state_cache = ToolbarOAuthStateCache()


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


def normalize_and_validate_app_url(team: Team, app_url: str) -> str:
    try:
        parsed = urlparse(app_url)
    except ValueError as exc:
        raise ToolbarOAuthError("invalid_app_url", "Invalid app_url", 400) from exc

    if not parsed.scheme or not parsed.hostname:
        raise ToolbarOAuthError("invalid_app_url", "app_url must include scheme and host", 400)

    if parsed.scheme not in ["http", "https"]:
        raise ToolbarOAuthError("invalid_app_url", "app_url must use http or https", 400)

    if parsed.scheme == "http" and not is_loopback_host(parsed.hostname):
        raise ToolbarOAuthError("invalid_app_url", "app_url must use https for non-loopback hosts", 400)

    if not team or not unparsed_hostname_in_allowed_url_list(team.app_urls, app_url):
        raise ToolbarOAuthError("forbidden_app_url", "Can only redirect to a permitted domain.", 403)

    # preserve path/query/fragment
    return app_url


def get_or_create_toolbar_oauth_application(user: User) -> OAuthApplication:
    """
    Return the toolbar OAuth app for the user's organization.

    The app is org-scoped so organizations do not share client IDs.
    The redirect URI is derived from settings.SITE_URL.
    """
    redirect_uri = _get_redirect_uri()
    app_name = settings.TOOLBAR_OAUTH_APPLICATION_NAME

    if user.organization is None:
        raise ToolbarOAuthError("no_organization", "User has no organization", 400)

    # Serialize first-time app creation per org to avoid duplicate rows under
    # concurrent requests (no unique DB constraint exists for this shape).
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=user.organization.pk)

        existing = OAuthApplication.objects.filter(
            organization=user.organization,
            name=app_name,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        ).first()

        if existing:
            if existing.redirect_uris != redirect_uri:
                existing.redirect_uris = redirect_uri
                existing.save(update_fields=["redirect_uris"])
            return existing

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
    toolbar_oauth_state_cache.mark_pending(nonce)
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

    toolbar_oauth_state_cache.claim_or_raise(nonce)

    if payload.get("user_id") != request_user.pk:
        raise ToolbarOAuthError("state_user_mismatch", "OAuth state user mismatch", 400)

    if payload.get("team_id") != request_team.pk:
        raise ToolbarOAuthError("state_team_mismatch", "OAuth state team mismatch", 400)

    app_url = payload.get("app_url")
    if not app_url:
        raise ToolbarOAuthError("invalid_state", "OAuth state is missing app_url", 400)
    normalize_and_validate_app_url(request_team, app_url)
    return payload


def build_authorization_url(
    application: OAuthApplication,
    state: str,
    code_challenge: str,
) -> str:
    redirect_uri = _get_redirect_uri()
    scopes = " ".join(settings.TOOLBAR_OAUTH_SCOPES)

    params = {
        "client_id": application.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": scopes,
    }

    return f"{settings.SITE_URL}/oauth/authorize/?{urlencode(params)}"


def exchange_code_for_tokens(
    client_id: str,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens by calling the token endpoint."""
    redirect_uri = _get_redirect_uri()
    token_url = f"{settings.SITE_URL}/oauth/token/"

    response = requests.post(
        token_url,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        timeout=settings.TOOLBAR_OAUTH_EXCHANGE_TIMEOUT_SECONDS,
    )

    try:
        payload = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        raise ToolbarOAuthError("token_exchange_failed", "Non-JSON response from token endpoint", 502)

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


def refresh_tokens(
    client_id: str,
    refresh_token: str,
) -> dict[str, Any]:
    """Exchange a refresh token for new access + refresh tokens."""
    token_url = f"{settings.SITE_URL}/oauth/token/"

    response = requests.post(
        token_url,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        },
        timeout=settings.TOOLBAR_OAUTH_EXCHANGE_TIMEOUT_SECONDS,
    )

    try:
        payload = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        raise ToolbarOAuthError("token_refresh_failed", "Non-JSON response from token endpoint", 502)

    if response.status_code >= 400:
        error = payload.get("error", "token_refresh_failed")
        detail = payload.get("error_description", "OAuth token refresh failed")
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
