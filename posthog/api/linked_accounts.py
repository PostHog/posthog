"""Personal Settings → Linked accounts: list/patch/disconnect, plus GitHub link flow.

A PostHog user's external-provider state lives in two tables:

* ``UserSocialIdentity`` — identity mapping (for task attribution, reviewer
  suggestions, etc.). Multiple PostHog users may point at the same external uid.
* ``UserSocialAuth`` (python-social-auth) — login credential. At most one
  PostHog user may hold a ``UserSocialAuth`` row for a given provider+uid.

A user with login enabled has **both** rows. Identity-only users have only
``UserSocialIdentity``. For backward compatibility, a ``UserSocialAuth``
without a matching ``UserSocialIdentity`` is treated as if both exist.

GitHub linking uses a dedicated OAuth flow that bypasses social-auth's login
pipeline, so SSO-enforced users can still map their identity without gaining
sign-in rights.
"""

from typing import Any, Literal, TypedDict
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_http_methods

import requests
import structlog
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from social_django.models import UserSocialAuth

from posthog.auth import SessionAuthentication, session_auth_required
from posthog.models.integration import GitHubIntegration
from posthog.models.user import User
from posthog.models.user_social_identity import (
    GITHUB_PROVIDER,
    UserSocialIdentity,
    apply_github_authorization,
    available_providers_for_user,
    can_disconnect_provider,
    can_user_enable_login_for,
    sso_enforcement_for,
)
from posthog.rate_limit import UserAuthenticationThrottle

logger = structlog.get_logger(__name__)

GITHUB_LINK_STATE_CACHE_PREFIX = "github_link_state:"
GITHUB_LINK_STATE_TTL_SECONDS = 10 * 60

# Frontend route for the personal Settings → Linked accounts section.
LINKED_ACCOUNTS_SETTINGS_PATH = "/settings/user-linked-accounts"

PROVIDER_DISPLAY_NAMES = {
    "google-oauth2": "Google",
    "github": "GitHub",
    "gitlab": "GitLab",
    "saml": "SAML",
}

ConnectFlow = Literal["github_link", "social_login"]


class ConnectInstructions(TypedDict):
    connect_flow: ConnectFlow | None
    connect_path: str | None


def _connect_instructions(provider: str) -> ConnectInstructions:
    """Where the frontend should send the user to start connecting this provider.

    GitHub uses the identity-only link flow so SSO-enforced users can still link
    GitHub for attribution without completing a sign-in. Other OAuth providers use
    social-auth's standard login pipeline. SAML can't be initiated from a button.
    """
    if provider == GITHUB_PROVIDER:
        return {
            "connect_flow": "github_link",
            "connect_path": "/api/users/@me/linked_accounts/github/start/",
        }
    if provider == "saml":
        return {"connect_flow": None, "connect_path": None}
    return {"connect_flow": "social_login", "connect_path": f"/login/{provider}/"}


def _serialize_linked_account(
    user: User,
    provider: str,
    identity: UserSocialIdentity | None,
    sa: UserSocialAuth | None,
    *,
    enforcement: str | None,
) -> dict[str, Any]:
    """Build the row payload for a single provider."""
    display_name = PROVIDER_DISPLAY_NAMES.get(provider, provider)
    enforcement_allows_login = enforcement is None or enforcement == provider
    connected = identity is not None or sa is not None

    if not connected:
        return {
            "provider": provider,
            "display_name": display_name,
            "connected": False,
            "account_identifier": None,
            "login_enabled": None,
            "can_enable_login": enforcement_allows_login,
            "can_disconnect": False,
            "created_at": None,
            "modified_at": None,
            **_connect_instructions(provider),
        }

    # Prefer identity's extra_data; fall back to social_auth (backward compat).
    extra = identity.extra_data if identity else (sa.extra_data if sa else None)
    account_id = None
    if isinstance(extra, dict):
        account_id = extra.get("login") or extra.get("email") or extra.get("username")

    created = identity.created_at if identity else (sa.created if sa else None)
    modified = identity.updated_at if identity else (sa.modified if sa else None)

    return {
        "provider": provider,
        "display_name": display_name,
        "connected": True,
        "account_identifier": account_id,
        "login_enabled": sa is not None,
        "can_enable_login": enforcement_allows_login,
        "can_disconnect": enforcement != provider and can_disconnect_provider(user, provider),
        "created_at": created,
        "modified_at": modified,
        "connect_flow": None,
        "connect_path": None,
    }


class LinkedAccountUpdateSerializer(serializers.Serializer):
    login_enabled = serializers.BooleanField()


class LinkedAccountsViewSet(viewsets.ViewSet):
    """``/api/users/@me/linked_accounts/`` — list/update/delete and kick off GitHub link.

    Session-only: identity mapping is sensitive and must never be mutated by
    personal API keys or OAuth bearer tokens. Implicitly scoped to ``request.user``.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete"]
    lookup_field = "provider"
    lookup_value_regex = r"[\w-]+"

    def _get_user(self) -> User:
        return self.request.user  # type: ignore[return-value]

    def _serialize_all(self, user: User) -> list[dict[str, Any]]:
        enforcement = sso_enforcement_for(user)
        available = available_providers_for_user(user)
        identities = {i.provider: i for i in UserSocialIdentity.objects.filter(user=user)}
        social_auths = {sa.provider: sa for sa in user.social_auth.all()}

        # Surface stray historical rows for providers no longer available instance-wide.
        all_connected = set(identities.keys()) | set(social_auths.keys())
        if enforcement is None:
            for provider in all_connected:
                if provider not in available:
                    available.append(provider)

        return [
            _serialize_linked_account(user, p, identities.get(p), social_auths.get(p), enforcement=enforcement)
            for p in available
        ]

    def _enforcement_response_fields(self, user: User) -> dict[str, Any]:
        enforcement = sso_enforcement_for(user)
        return {
            "sso_enforcement": enforcement,
            "sso_enforcement_provider_name": (
                PROVIDER_DISPLAY_NAMES.get(enforcement, enforcement) if enforcement else None
            ),
        }

    def list(self, request: Request) -> Response:
        user = self._get_user()
        return Response(
            {
                "results": self._serialize_all(user),
                **self._enforcement_response_fields(user),
            }
        )

    def partial_update(self, request: Request, provider: str) -> Response:
        user = self._get_user()

        serializer = LinkedAccountUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        desired = serializer.validated_data["login_enabled"]

        identity = UserSocialIdentity.objects.filter(user=user, provider=provider).first()
        sa = user.social_auth.filter(provider=provider).first()

        if identity is None and sa is None:
            raise exceptions.NotFound("No linked account for this provider.")

        if desired:
            if sa is None:
                # Enable login: create UserSocialAuth from identity.
                if not can_user_enable_login_for(user, provider):
                    raise exceptions.PermissionDenied(
                        "Sign-in with this provider is blocked by your organization's SSO enforcement."
                    )
                uid = identity.uid if identity else None
                if not uid:
                    raise exceptions.ValidationError("Cannot determine account UID.")
                # Only one user may have login for a given provider+uid.
                if UserSocialAuth.objects.filter(provider=provider, uid=uid).exists():
                    raise exceptions.PermissionDenied("Another account already uses this external account for sign-in.")
                UserSocialAuth.objects.create(
                    user=user,
                    provider=provider,
                    uid=uid,
                    extra_data=identity.extra_data if identity else {},
                )
        else:
            if sa is not None:
                # Disable login: ensure identity row exists (backfill), then delete social_auth.
                if identity is None:
                    UserSocialIdentity.objects.create(
                        user=user,
                        provider=provider,
                        uid=sa.uid,
                        extra_data=sa.extra_data or {},
                    )
                sa.delete()

        # Re-fetch for response.
        identity = UserSocialIdentity.objects.filter(user=user, provider=provider).first()
        sa = user.social_auth.filter(provider=provider).first()
        enforcement = sso_enforcement_for(user)
        return Response(_serialize_linked_account(user, provider, identity, sa, enforcement=enforcement))

    def destroy(self, request: Request, provider: str) -> Response:
        user = self._get_user()
        identity = UserSocialIdentity.objects.filter(user=user, provider=provider).first()
        sa = user.social_auth.filter(provider=provider).first()

        if identity is None and sa is None:
            raise exceptions.NotFound("No linked account for this provider.")

        if not can_disconnect_provider(user, provider):
            raise exceptions.PermissionDenied(
                "This account is required by your organization's SSO enforcement and can't be disconnected."
            )

        # Guardrail: don't strand users who rely on this social login.
        if sa is not None and not user.has_usable_password():
            has_other_login = user.social_auth.exclude(provider=provider).exists()
            if not has_other_login:
                raise exceptions.ValidationError(
                    "Set a password or link another sign-in method before disconnecting this account."
                )

        if sa is not None:
            sa.delete()
        if identity is not None:
            if provider == GITHUB_PROVIDER:
                _revoke_github_user_authorization(identity)
            identity.delete()

        return Response(
            {
                "results": self._serialize_all(user),
                **self._enforcement_response_fields(user),
            }
        )

    @action(
        methods=["POST"],
        detail=False,
        url_path="github/start",
        throttle_classes=[UserAuthenticationThrottle],
    )
    def github_start(self, request: Request) -> Response:
        """Initiates a link-only GitHub OAuth flow. Returns ``{authorize_url}``."""
        client_id = settings.GITHUB_APP_CLIENT_ID
        if not client_id:
            raise exceptions.ValidationError("GitHub linking is not configured on this instance.")

        state = get_random_string(48)
        cache.set(
            f"{GITHUB_LINK_STATE_CACHE_PREFIX}{state}",
            {"user_id": self._get_user().id},
            timeout=GITHUB_LINK_STATE_TTL_SECONDS,
        )
        params = urlencode(
            {
                "client_id": client_id,
                "state": state,
                "redirect_uri": request.build_absolute_uri("/complete/github-link/"),
            }
        )
        return Response({"authorize_url": f"https://github.com/login/oauth/authorize?{params}"})


def _revoke_github_user_authorization(identity: UserSocialIdentity) -> None:
    """Best-effort revoke of the stored GitHub user token on disconnect.

    Row deletion is the source of truth; revoke failures are swallowed so a
    transient GitHub outage doesn't block the user from disconnecting.
    """
    access_token = identity.access_token
    client_id = settings.GITHUB_APP_CLIENT_ID
    client_secret = settings.GITHUB_APP_OAUTH_CLIENT_SECRET
    if not access_token or not client_id or not client_secret:
        return
    try:
        requests.delete(
            f"https://api.github.com/applications/{client_id}/grant",
            auth=(client_id, client_secret),
            json={"access_token": access_token},
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=5,
        )
    except Exception:
        logger.warning("linked_accounts: failed to revoke GitHub user authorization", exc_info=True)


@require_http_methods(["GET"])
@session_auth_required
def github_link_complete(request: HttpRequest) -> HttpResponseRedirect:
    """GitHub OAuth callback for the identity link flow.

    Creates a ``UserSocialIdentity`` row and stashes the user-to-server tokens
    returned by the exchange — those later power user-authored PostHog Code
    runs. No ``UserSocialAuth`` row is created here, so linking does not grant
    sign-in rights by itself (the user opts into login separately via the
    Settings toggle).

    Multiple PostHog users may link to the same GitHub uid this way. If the user
    already had a ``UserSocialAuth`` for a *different* GitHub uid, that stale
    login row is removed.

    Note: this is GitHub's *authorization* endpoint, not a second *installation*
    flow — the user sees a consent screen, not a repo picker. The returned
    user-to-server token's scope is computed at call time as (App installations
    the user has permission to use) ∩ (the user's GitHub permissions). Repo
    coverage is governed by the team ``Integration``'s installation selection;
    if the user has GitHub access to a repo that the team installation covers,
    the UTS works there with no extra consent.
    """
    error_redirect = redirect(f"{LINKED_ACCOUNTS_SETTINGS_PATH}?github_link_error=1")

    code = request.GET.get("code")
    state = request.GET.get("state")
    if not code or not state:
        return error_redirect

    cache_key = f"{GITHUB_LINK_STATE_CACHE_PREFIX}{state}"
    state_payload = cache.get(cache_key)
    if not state_payload or state_payload.get("user_id") != request.user.id:
        return error_redirect
    cache.delete(cache_key)

    authorization = GitHubIntegration.github_user_from_code(code)
    if authorization is None:
        return error_redirect

    # Invalidate any stale login row pointing at a different GitHub account. Skip the delete
    # if it would strand a user whose only sign-in method is this UserSocialAuth — they'd have
    # no way back into PostHog after the redirect. The Settings UI surfaces this as an actionable
    # error so they can set a password or link another provider first.
    old_sa = UserSocialAuth.objects.filter(user=request.user, provider=GITHUB_PROVIDER).first()
    if old_sa and old_sa.uid != str(authorization.gh_id):
        if not request.user.has_usable_password():
            has_other_login = request.user.social_auth.exclude(provider=GITHUB_PROVIDER).exists()
            if not has_other_login:
                return redirect(f"{LINKED_ACCOUNTS_SETTINGS_PATH}?github_link_error=would_disable_only_login")
        old_sa.delete()

    identity, _ = UserSocialIdentity.objects.get_or_create(
        user=request.user,
        provider=GITHUB_PROVIDER,
        defaults={"uid": str(authorization.gh_id)},
    )
    # Keep uid in sync if the user re-authorized with a different GitHub account.
    if identity.uid != str(authorization.gh_id):
        identity.uid = str(authorization.gh_id)
    apply_github_authorization(
        identity,
        gh_id=authorization.gh_id,
        gh_login=authorization.gh_login,
        access_token=authorization.access_token,
        refresh_token=authorization.refresh_token,
        access_token_expires_in=authorization.access_token_expires_in,
        refresh_token_expires_in=authorization.refresh_token_expires_in,
    )
    return redirect(f"{LINKED_ACCOUNTS_SETTINGS_PATH}?github_link_success=1")
