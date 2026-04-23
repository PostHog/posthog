"""Personal Settings → Linked accounts: manage the user's own GitHub integration.

A ``UserIntegration`` (kind=github) stores the user's own GitHub App installation
plus user-to-server tokens. This gives the user independent repo access at the
personal level, separate from any team-level ``Integration``.

Login management is fully handled by ``UserSocialAuth`` (python-social-auth) and
is not controlled here.
"""

from typing import Any, cast
from urllib.parse import urlencode

from django.core.cache import cache
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

import structlog
from rest_framework import exceptions, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import SessionAuthentication, session_auth_required
from posthog.models.instance_setting import get_instance_settings
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.user import User
from posthog.models.user_integration import (
    UserGitHubIntegration,
    UserIntegration,
    user_github_integration_from_installation,
)
from posthog.rate_limit import UserAuthenticationThrottle

logger = structlog.get_logger(__name__)

GITHUB_INSTALL_STATE_CACHE_PREFIX = "github_user_install_state:"
GITHUB_INSTALL_STATE_TTL_SECONDS = 10 * 60

# Frontend route for the personal Settings → Linked accounts section.
LINKED_ACCOUNTS_SETTINGS_PATH = "/settings/user-linked-accounts"


def _serialize_github_integration(
    integration: UserIntegration | None,
    *,
    team_integration_installation_ids: set[str],
) -> dict[str, Any]:
    """Build the response payload for the user's GitHub integration."""
    if integration is None:
        return {
            "kind": "github",
            "connected": False,
            "account_identifier": None,
            "installation_id": None,
            "repository_selection": None,
            "account": None,
            "uses_shared_installation": False,
            "created_at": None,
        }

    github = UserGitHubIntegration(integration)
    return {
        "kind": "github",
        "connected": True,
        "account_identifier": github.github_login,
        "installation_id": integration.integration_id,
        "repository_selection": integration.config.get("repository_selection"),
        "account": integration.config.get("account"),
        "uses_shared_installation": (
            integration.integration_id is not None and integration.integration_id in team_integration_installation_ids
        ),
        "created_at": integration.created_at,
    }


class LinkedAccountsViewSet(viewsets.ViewSet):
    """``/api/users/@me/linked_accounts/`` — manage the user's GitHub integration.

    Session-only: integration management is sensitive and must never be mutated
    by personal API keys or OAuth bearer tokens. Implicitly scoped to ``request.user``.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete"]
    lookup_field = "kind"
    lookup_value_regex = r"[\w-]+"

    def _get_user(self) -> User:
        return cast(User, self.request.user)

    def _team_github_context(self, user: User) -> dict[str, Any]:
        """Fetch the current team's GitHub integrations for context."""
        team = user.current_team
        if team is None:
            return {"team_github_integrations": [], "_installation_ids": set()}

        team_integrations = Integration.objects.filter(team=team, kind="github").values("integration_id", "config")
        result = []
        installation_ids: set[str] = set()
        for ti in team_integrations:
            iid = ti["integration_id"]
            if iid:
                installation_ids.add(str(iid))
            config = ti["config"] or {}
            account = config.get("account", {})
            result.append({"installation_id": iid, "account_name": account.get("name")})
        return {"team_github_integrations": result, "_installation_ids": installation_ids}

    def list(self, request: Request) -> Response:
        user = self._get_user()
        integration = UserIntegration.objects.filter(user=user, kind="github").first()
        team_ctx = self._team_github_context(user)
        return Response(
            {
                "results": [
                    _serialize_github_integration(
                        integration, team_integration_installation_ids=team_ctx["_installation_ids"]
                    )
                ],
                "team_github_integrations": team_ctx["team_github_integrations"],
            }
        )

    def destroy(self, request: Request, kind: str) -> Response:
        user = self._get_user()
        if kind != "github":
            raise exceptions.NotFound("Only GitHub integrations are supported.")

        integration = UserIntegration.objects.filter(user=user, kind="github").first()
        if integration is None:
            raise exceptions.NotFound("No GitHub integration found.")

        integration.delete()

        team_ctx = self._team_github_context(user)
        return Response(
            {
                "results": [
                    _serialize_github_integration(None, team_integration_installation_ids=team_ctx["_installation_ids"])
                ],
                "team_github_integrations": team_ctx["team_github_integrations"],
            }
        )

    @action(methods=["GET"], detail=False, url_path="github/repos")
    def github_repos(self, request: Request) -> Response:
        """List repositories accessible to the user's GitHub integration."""
        user = self._get_user()
        integration = UserIntegration.objects.filter(user=user, kind="github").first()
        if integration is None:
            raise exceptions.NotFound("No GitHub integration found.")

        github = UserGitHubIntegration(integration)
        repos = github.list_repository_names()
        return Response({"repositories": repos})

    @action(
        methods=["POST"],
        detail=False,
        url_path="github/start",
        throttle_classes=[UserAuthenticationThrottle],
    )
    def github_start(self, request: Request) -> Response:
        """Initiate a GitHub App installation flow. Returns ``{install_url}``.

        The user is sent to GitHub's App installation page where they select an
        account and repos. GitHub redirects back with ``installation_id`` and
        ``code`` (user authorization) to our callback endpoint.
        """
        instance_settings = get_instance_settings(["GITHUB_APP_SLUG"])
        app_slug = instance_settings.get("GITHUB_APP_SLUG")
        if not app_slug:
            raise exceptions.ValidationError("GitHub App is not configured on this instance (missing GITHUB_APP_SLUG).")

        from django.utils.crypto import get_random_string

        token = get_random_string(48)

        cache.set(
            f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}",
            {"user_id": request.user.id},
            timeout=GITHUB_INSTALL_STATE_TTL_SECONDS,
        )
        # Encode the state in the same format as team integrations (URL-encoded
        # query string with `token`), plus `source=linked_accounts` so the frontend
        # callback handler knows to redirect to the user-level backend endpoint
        # instead of creating a team integration.
        state = urlencode({"token": token, "source": "linked_accounts"})
        params = urlencode({"state": state})
        return Response({"install_url": f"https://github.com/apps/{app_slug}/installations/new?{params}"})


@require_http_methods(["GET"])
@session_auth_required
def github_link_complete(request: HttpRequest) -> HttpResponseRedirect:
    """GitHub App installation + authorization callback.

    After the user installs the GitHub App and authorizes it, GitHub redirects
    here with ``installation_id``, ``code``, and ``state``. We:

    1. Validate the state parameter.
    2. Fetch installation info and access token from ``installation_id``.
    3. Exchange ``code`` for user-to-server tokens.
    4. Create/update a ``UserIntegration`` with both token sets.
    """

    def _error(reason: str) -> HttpResponseRedirect:
        logger.warning("github_link: redirecting with error", reason=reason, user_id=request.user.id)
        return redirect(f"{LINKED_ACCOUNTS_SETTINGS_PATH}?github_link_error={reason}")

    # GitHub appends ?error=... when the user denied consent.
    if github_error := request.GET.get("error"):
        logger.warning(
            "github_link: GitHub returned error on callback",
            error=github_error,
            description=request.GET.get("error_description"),
            user_id=request.user.id,
        )
        return _error(github_error if github_error == "access_denied" else "github_oauth_error")

    installation_id = request.GET.get("installation_id")
    code = request.GET.get("code")
    state = request.GET.get("state")

    if not installation_id or not code or not state:
        return _error("missing_params")

    # Validate state
    cache_key = f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{state}"
    state_payload = cache.get(cache_key)
    if not state_payload or state_payload.get("user_id") != request.user.id:
        return _error("invalid_state")
    cache.delete(cache_key)

    # Exchange code for user-to-server tokens
    authorization = GitHubIntegration.github_user_from_code(code)
    if authorization is None:
        return _error("exchange_failed")

    # Get installation info and access token
    try:
        installation_info = GitHubIntegration.client_request(f"installations/{installation_id}").json()
        access_token_response = GitHubIntegration.client_request(
            f"installations/{installation_id}/access_tokens", method="POST"
        ).json()
    except Exception:
        logger.warning("github_link: failed to fetch installation info", exc_info=True)
        return _error("installation_fetch_failed")

    installation_access_token = access_token_response.get("token")
    if not installation_access_token:
        return _error("installation_token_failed")

    user_github_integration_from_installation(
        request.user,
        installation_id=installation_id,
        installation_info=installation_info,
        installation_access_token=installation_access_token,
        installation_token_expires_at=access_token_response["expires_at"],
        repository_selection=access_token_response.get("repository_selection", "selected"),
        gh_id=authorization.gh_id,
        gh_login=authorization.gh_login,
        user_access_token=authorization.access_token,
        user_refresh_token=authorization.refresh_token,
        user_access_token_expires_in=authorization.access_token_expires_in,
        user_refresh_token_expires_in=authorization.refresh_token_expires_in,
    )

    return redirect(f"{LINKED_ACCOUNTS_SETTINGS_PATH}?github_link_success=1")
