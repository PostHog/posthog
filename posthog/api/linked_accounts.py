"""Personal Settings → Personal integrations: manage the user's own GitHub integrations.

A ``UserIntegration`` (kind=github) stores the user's own GitHub App installation
plus user-to-server tokens. This gives the user independent repo access at the
personal level, separate from any team-level ``Integration``.

A user may have multiple GitHub integrations (one per GitHub App installation),
allowing coverage of repos across personal accounts and multiple organisations.

Login management is fully handled by ``UserSocialAuth`` (python-social-auth) and
is not controlled here.
"""

import re
from typing import Any, cast
from urllib.parse import parse_qs, urlencode

from django.core.cache import cache
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

import requests
import structlog
from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.integration import GitHubReposQuerySerializer
from posthog.auth import SessionAuthentication, session_auth_required
from posthog.models.instance_setting import get_instance_settings
from posthog.models.integration import GitHubInstallationAccess, GitHubIntegration, Integration
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

# Frontend route for the personal Settings → Personal integrations section.
PERSONAL_INTEGRATIONS_SETTINGS_PATH = "/settings/user-personal-integrations"


def _serialize_github_integration(
    integration: UserIntegration,
    *,
    team_integration_installation_ids: set[str],
) -> dict[str, Any]:
    """Build the response payload for a single GitHub UserIntegration."""
    return {
        "kind": "github",
        "installation_id": integration.external_id,
        "repository_selection": integration.config.get("repository_selection"),
        "account": integration.config.get("account"),
        "uses_shared_installation": (
            integration.external_id is not None and integration.external_id in team_integration_installation_ids
        ),
        "created_at": integration.created_at,
    }


class LinkedAccountsViewSet(viewsets.ViewSet):
    """``/api/users/@me/integrations/`` — manage the user's GitHub integrations.

    Session-only: integration management is sensitive and must never be mutated
    by personal API keys or OAuth bearer tokens. Implicitly scoped to ``request.user``.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete"]

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
            if not iid:
                continue
            installation_ids.add(str(iid))
            config = ti["config"] or {}
            account = config.get("account", {})
            result.append({"installation_id": str(iid), "account_name": account.get("name")})
        return {"team_github_integrations": result, "_installation_ids": installation_ids}

    def list(self, request: Request) -> Response:
        user = self._get_user()
        integrations = UserIntegration.objects.filter(user=user, kind="github").order_by("created_at")
        team_ctx = self._team_github_context(user)
        return Response(
            {
                "results": [
                    _serialize_github_integration(
                        integration, team_integration_installation_ids=team_ctx["_installation_ids"]
                    )
                    for integration in integrations
                ],
                "team_github_integrations": team_ctx["team_github_integrations"],
            }
        )

    @action(methods=["DELETE"], detail=False, url_path=r"github/(?P<installation_id>\d+)")
    def github_destroy(self, request: Request, installation_id: str) -> Response:
        """Remove a specific GitHub installation by its installation_id."""
        user = self._get_user()
        integration = UserIntegration.objects.filter(user=user, kind="github", external_id=installation_id).first()
        if integration is None:
            raise exceptions.NotFound("No GitHub integration found for this installation.")
        integration.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["GET"], detail=False, url_path=r"github/(?P<installation_id>\d+)/repos")
    def github_repos(self, request: Request, installation_id: str) -> Response:
        """List repositories accessible to a specific GitHub installation (paginated, cached)."""
        query_serializer = GitHubReposQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        search = query_serializer.validated_data["search"]
        limit = query_serializer.validated_data["limit"]
        offset = query_serializer.validated_data["offset"]

        integration = UserIntegration.objects.filter(
            user=self._get_user(), kind="github", external_id=installation_id
        ).first()
        if integration is None:
            raise exceptions.NotFound("No GitHub integration found for this installation.")

        github = UserGitHubIntegration(integration)
        repositories, has_more = github.list_cached_repositories(search=search, limit=limit, offset=offset)
        return Response({"repositories": repositories, "has_more": has_more})

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
        return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?github_link_error={reason}")

    # GitHub appends ?error=... when the user denied consent.
    if github_error := request.GET.get("error"):
        logger.warning(
            "github_link: GitHub returned error on callback",
            error=github_error,
            description=request.GET.get("error_description"),
            user_id=request.user.id,
        )
        return _error(github_error if github_error == "access_denied" else "github_oauth_error")

    # nosemgrep: python.django.security.injection.ssrf.ssrf-injection-requests.ssrf-injection-requests -- validated as digits-only below before any URL construction
    installation_id = request.GET.get("installation_id")
    code = request.GET.get("code")
    state_raw = request.GET.get("state")

    if not installation_id or not code or not state_raw:
        return _error("missing_params")

    # installation_id must be a plain positive integer (GitHub App IDs always are).
    # Reject anything else before it touches URL construction.
    if not re.fullmatch(r"\d{1,20}", installation_id):
        return _error("invalid_installation_id")

    # The frontend extracts the raw token from the URL-encoded state before forwarding
    # here, so state_raw is normally the 48-char random token.  Handle both forms so
    # direct backend calls (e.g. in tests) and any future flow changes work correctly.
    state_params = parse_qs(state_raw)
    if "token" in state_params:
        token = state_params["token"][0]
    else:
        token = state_raw

    # Validate state
    cache_key = f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}"
    state_payload = cache.get(cache_key)
    if not state_payload or state_payload.get("user_id") != request.user.id:
        return _error("invalid_state")
    cache.delete(cache_key)

    # Exchange code for user-to-server tokens
    authorization = GitHubIntegration.github_user_from_code(code)
    if authorization is None:
        return _error("exchange_failed")

    # Verify the authorizing user actually has access to this installation.
    # An attacker could use their own OAuth code with someone else's installation_id
    # to obtain an installation token scoped to a different organisation's repos.
    try:
        verify_response = requests.get(  # nosemgrep: python.django.security.injection.ssrf.ssrf-injection-requests.ssrf-injection-requests -- installation_id is validated as digits-only above
            f"https://api.github.com/user/installations/{installation_id}/repositories",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {authorization.access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"per_page": 1},
            timeout=10,
        )
        if verify_response.status_code == 404:
            logger.warning(
                "github_link: user does not have access to installation",
                installation_id=installation_id,
                user_id=request.user.id,
            )
            return _error("installation_not_authorized")
    except Exception:
        logger.warning("github_link: installation ownership check failed", exc_info=True)
        # Don't fail on a transient API error; proceed optimistically.

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

    token_expires_at = access_token_response.get("expires_at")
    if not token_expires_at:
        return _error("installation_token_failed")

    user_github_integration_from_installation(
        request.user,
        GitHubInstallationAccess(
            installation_id=installation_id,
            installation_info=installation_info,
            access_token=installation_access_token,
            token_expires_at=token_expires_at,
            repository_selection=access_token_response.get("repository_selection", "selected"),
        ),
        authorization,
    )

    return redirect(f"{PERSONAL_INTEGRATIONS_SETTINGS_PATH}?github_link_success=1")
