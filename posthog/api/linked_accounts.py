"""Personal Settings → Linked accounts: list/patch/disconnect, plus GitHub link flow.

Storage stays on ``UserSocialAuth`` — identity lives alongside auth. This module
adds a GitHub link path that deliberately bypasses the social-auth *login*
pipeline, so SSO-enforced users can still map their PostHog account to a
GitHub identity (for task attribution, reviewer suggestions, etc.) without
requesting the right to sign in via GitHub.
"""

from typing import Any, Literal, TypedDict
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_http_methods

from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from social_django.models import UserSocialAuth

from posthog.auth import SessionAuthentication, session_auth_required
from posthog.models.integration import GitHubIntegration
from posthog.models.user import User
from posthog.models.user_social_auth_login_preference import (
    GITHUB_PROVIDER,
    UserSocialAuthLoginPreference,
    available_providers_for_user,
    can_disconnect_provider,
    can_user_enable_login_for,
    effective_login_enabled,
    sso_enforcement_for,
)
from posthog.rate_limit import UserAuthenticationThrottle

GITHUB_LINK_STATE_CACHE_PREFIX = "github_link_state:"
GITHUB_LINK_STATE_TTL_SECONDS = 10 * 60

# Frontend route for the personal Settings → Linked accounts section. Kept here
# (rather than as a literal in callbacks) so a future rename happens in one place.
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

    GitHub uses the identity-only link flow (two-step: POST to get authorize_url, then
    redirect) so SSO-enforced users can still link GitHub for attribution without
    completing a sign-in. Other OAuth providers use social-auth's standard login
    pipeline, which associates the returning ``UserSocialAuth`` row with the
    already-authenticated PostHog user.

    SAML returns ``(None, None)`` because SAML linking can't be initiated from a button:
    ``MultitenantSAMLAuth.auth_url`` requires an ``email`` query param and reads from
    ``strategy.request_data()``. SAML rows materialize via an actual SAML sign-in.
    """
    if provider == GITHUB_PROVIDER:
        return {
            "connect_flow": "github_link",
            "connect_path": "/api/linked_accounts/github/start/",
        }
    if provider == "saml":
        return {"connect_flow": None, "connect_path": None}
    return {"connect_flow": "social_login", "connect_path": f"/login/{provider}/"}


def _serialize_linked_account(
    user: User,
    provider: str,
    sa: UserSocialAuth | None,
    *,
    enforcement: str | None,
) -> dict[str, Any]:
    """Build the row payload. ``enforcement`` is resolved once per request by the
    caller and threaded in to avoid an OrganizationDomain lookup per provider.
    """
    display_name = PROVIDER_DISPLAY_NAMES.get(provider, provider)
    enforcement_allows_login = enforcement is None or enforcement == provider
    if sa is None:
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

    login = None
    if isinstance(sa.extra_data, dict):
        login = sa.extra_data.get("login") or sa.extra_data.get("email") or sa.extra_data.get("username")
    return {
        "provider": provider,
        "display_name": display_name,
        "connected": True,
        "account_identifier": login,
        "login_enabled": _effective_login_enabled_with_enforcement(sa, enforcement),
        "can_enable_login": enforcement_allows_login,
        "can_disconnect": enforcement != provider and can_disconnect_provider(user, provider),
        "created_at": sa.created,
        "modified_at": sa.modified,
        "connect_flow": None,
        "connect_path": None,
    }


def _effective_login_enabled_with_enforcement(sa: UserSocialAuth, enforcement: str | None) -> bool:
    """Like :func:`effective_login_enabled` but uses the pre-resolved ``enforcement``
    value to skip an extra ``OrganizationDomain`` query per row."""
    try:
        return sa.login_preference.login_enabled
    except UserSocialAuthLoginPreference.DoesNotExist:
        if enforcement is not None:
            return enforcement == sa.provider
        return True


class LinkedAccountUpdateSerializer(serializers.Serializer):
    login_enabled = serializers.BooleanField()


class LinkedAccountsViewSet(viewsets.ViewSet):
    """``/api/linked_accounts/`` — list/update/delete and kick off GitHub link.

    Session-only: identity mapping is sensitive and must never be mutated by
    personal API keys or OAuth bearer tokens. Implicitly scoped to ``request.user``.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete"]
    # Provider is a snake-case/hyphenated string (e.g. ``google-oauth2``) — override the
    # default numeric pk lookup so the router builds `<provider>` path converters correctly.
    lookup_field = "provider"
    lookup_value_regex = r"[\w-]+"

    def _get_user(self) -> User:
        return self.request.user  # type: ignore[return-value]

    def _serialize_all(self, user: User) -> list[dict[str, Any]]:
        enforcement = sso_enforcement_for(user)
        available = available_providers_for_user(user)
        connected_by_provider = {sa.provider: sa for sa in user.social_auth.select_related("login_preference")}
        # Also surface any historical rows for providers no longer available instance-wide,
        # so users can still disconnect them. Hidden when SSO is enforced — only the enforced
        # provider is shown.
        if enforcement is None:
            for provider in connected_by_provider:
                if provider not in available:
                    available.append(provider)
        return [
            _serialize_linked_account(user, p, connected_by_provider.get(p), enforcement=enforcement) for p in available
        ]

    def list(self, request: Request) -> Response:
        user = self._get_user()
        enforcement = sso_enforcement_for(user)
        return Response(
            {
                "results": self._serialize_all(user),
                # Surface enforcement to the frontend so it can explain why the list is
                # narrowed to a single provider; falsy values render without the callout.
                "sso_enforcement": enforcement,
                "sso_enforcement_provider_name": (
                    PROVIDER_DISPLAY_NAMES.get(enforcement, enforcement) if enforcement else None
                ),
            }
        )

    def partial_update(self, request: Request, provider: str) -> Response:
        user = self._get_user()
        sa = user.social_auth.filter(provider=provider).select_related("login_preference").first()
        if sa is None:
            raise exceptions.NotFound("No linked account for this provider.")

        serializer = LinkedAccountUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        desired = serializer.validated_data["login_enabled"]

        if desired and not can_user_enable_login_for(user, provider):
            # Org policy (SSO enforcement) forbids enabling login for this provider.
            raise exceptions.PermissionDenied(
                "Sign-in with this provider is blocked by your organization's SSO enforcement."
            )

        UserSocialAuthLoginPreference.objects.update_or_create(
            social_auth=sa,
            defaults={"login_enabled": desired},
        )
        sa = user.social_auth.filter(provider=provider).select_related("login_preference").get()
        enforcement = sso_enforcement_for(user)
        return Response(_serialize_linked_account(user, provider, sa, enforcement=enforcement))

    def destroy(self, request: Request, provider: str) -> Response:
        user = self._get_user()
        sa = user.social_auth.filter(provider=provider).first()
        if sa is None:
            raise exceptions.NotFound("No linked account for this provider.")

        if not can_disconnect_provider(user, provider):
            raise exceptions.PermissionDenied(
                "This account is required by your organization's SSO enforcement and can't be disconnected."
            )

        # Guardrail: don't let users strand themselves if this is their only
        # way to sign in. They should set a password or another provider first.
        if not user.has_usable_password():
            other_login_enabled = any(
                effective_login_enabled(other)
                for other in user.social_auth.exclude(pk=sa.pk).select_related("login_preference")
            )
            if not other_login_enabled:
                raise exceptions.ValidationError(
                    "Set a password or link another sign-in method before disconnecting this account."
                )
        sa.delete()
        # Return the refreshed list (same shape as list()) so the client doesn't need a follow-up GET.
        enforcement = sso_enforcement_for(user)
        return Response(
            {
                "results": self._serialize_all(user),
                "sso_enforcement": enforcement,
                "sso_enforcement_provider_name": (
                    PROVIDER_DISPLAY_NAMES.get(enforcement, enforcement) if enforcement else None
                ),
            }
        )

    @action(
        methods=["POST"],
        detail=False,
        url_path="github/start",
        throttle_classes=[UserAuthenticationThrottle],
    )
    def github_start(self, request: Request) -> Response:
        """Initiates a link-only GitHub OAuth flow. Returns ``{authorize_url}``.

        Uses the same GitHub App OAuth credentials as the App install, but the
        callback is on PostHog's link route rather than social-auth's login
        pipeline — SSO enforcement does not intercept.
        """
        client_id = settings.GITHUB_APP_OAUTH_CLIENT_ID
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
                # no scope — we only need identity; default scope gives public profile
            }
        )
        return Response({"authorize_url": f"https://github.com/login/oauth/authorize?{params}"})


@require_http_methods(["GET"])
@session_auth_required
def github_link_complete(request: HttpRequest) -> HttpResponseRedirect:
    """GitHub OAuth callback for the link-only flow.

    Runs outside DRF/social-auth. Validates state, exchanges the code for
    ``(id, login)``, writes the ``UserSocialAuth`` row on the already-authenticated
    PostHog user, then redirects to the personal Settings page.
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

    result = GitHubIntegration.github_user_from_code(code)
    if result is None:
        return error_redirect
    gh_id, gh_login = result

    existing_owner = (
        UserSocialAuth.objects.filter(provider=GITHUB_PROVIDER, uid=str(gh_id)).exclude(user_id=request.user.id).first()
    )
    if existing_owner is not None:
        return redirect(f"{LINKED_ACCOUNTS_SETTINGS_PATH}?github_link_error=already_linked")

    sa, created = UserSocialAuth.objects.update_or_create(
        user=request.user,
        provider=GITHUB_PROVIDER,
        defaults={"uid": str(gh_id), "extra_data": {"login": gh_login, "id": gh_id}},
    )
    if created:
        # Brand-new GitHub link: opt out of sign-in by default (identity-only product policy).
        # If the row already existed (e.g. from a historical GH login), don't disturb the user's
        # current sign-in behavior — they can opt out manually via the Settings toggle.
        UserSocialAuthLoginPreference.objects.create(social_auth=sa, login_enabled=False)
    return redirect(f"{LINKED_ACCOUNTS_SETTINGS_PATH}?github_link_success=1")
