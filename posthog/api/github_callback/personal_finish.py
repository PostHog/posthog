"""GitHub App install + user authorization callback handler for personal integrations.

This is the view ``/complete/github-link/`` resolves to. The body is intentionally
straight-line: figure out which flow we are completing (default install, OAuth-only
fast path, OAuth discovery, or the team-orphan recovery flow), validate the
server-side state, exchange the OAuth ``code`` for tokens, and upsert the
``UserIntegration`` (and optionally the team ``Integration`` for the orphan flow).
"""

from typing import cast
from urllib.parse import urlencode

from django.core.cache import cache
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

import requests
import structlog

from posthog.api.github_callback import personal_state
from posthog.api.github_callback.redirects import PERSONAL_INTEGRATIONS_SETTINGS_PATH, final_github_redirect
from posthog.api.github_callback.types import (
    APP_CONNECT_FROM_VALUES,
    GITHUB_INSTALL_STATE_CACHE_PREFIX,
    github_oauth_redirect_uri,
    is_valid_github_installation_id,
)
from posthog.auth import session_auth_required
from posthog.models.integration import GitHubInstallationAccess, GitHubIntegration, Integration
from posthog.models.user import User
from posthog.models.user_integration import user_github_integration_from_installation

logger = structlog.get_logger(__name__)


def _app_connect_from_from_state_query(request: HttpRequest) -> str | None:
    """Best-effort: OAuth error callbacks may still include ``state``; read cache
    (do not delete) to recover which first-party client started the flow so the
    error redirect returns to the right place."""
    state_raw = request.GET.get("state")
    if not state_raw:
        return None
    token = personal_state.github_state_token(state_raw)
    cache_key = f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}"
    state_payload = cache.get(cache_key)
    if not state_payload or state_payload.get("user_id") != request.user.id:
        return None
    connect_from = state_payload.get("connect_from")
    return connect_from if connect_from in APP_CONNECT_FROM_VALUES else None


@require_http_methods(["GET"])
@session_auth_required
def github_link_complete(request: HttpRequest) -> HttpResponseRedirect:
    """GitHub App installation + user authorization callback.

    **Install flow** (``/installations/new``): GitHub sends ``installation_id``,
    ``code``, and ``state`` in the query string.

    **OAuth-only flow** (``/login/oauth/authorize`` when the team already has the
    app installed): GitHub sends only ``code`` and ``state``; ``installation_id``
    is read from validated server-side state.

    Steps: validate state, resolve ``installation_id``, exchange ``code`` for
    user-to-server tokens, fetch installation token, create/update ``UserIntegration``.
    """

    user = cast(User, request.user)

    # Which first-party client (if any) started this flow; controls the final
    # redirect destination. Resolved from validated server-side state below.
    connect_from_value: str | None = None

    def _error(reason: str) -> HttpResponseRedirect:
        logger.warning("github_link: redirecting with error", reason=reason, user_id=user.id)
        return final_github_redirect(connect_from_value, error=reason)

    # GitHub appends ?error=... when the user denied consent.
    if github_error := request.GET.get("error"):
        logger.warning(
            "github_link: GitHub returned error on callback",
            error=github_error,
            description=request.GET.get("error_description"),
            user_id=user.id,
        )
        connect_from_value = _app_connect_from_from_state_query(request)
        return _error(github_error if github_error == "access_denied" else "github_oauth_error")

    code = request.GET.get("code")
    state_raw = request.GET.get("state")

    if not code or not state_raw:
        return _error("missing_params")

    token = personal_state.github_state_token(state_raw)

    # Validate state
    cache_key = f"{GITHUB_INSTALL_STATE_CACHE_PREFIX}{token}"
    state_payload = cache.get(cache_key)
    if not state_payload or state_payload.get("user_id") != user.id:
        return _error("invalid_state")
    connect_from_value = state_payload.get("connect_from")
    cache.delete(cache_key)

    flow = state_payload.get("flow")
    oauth_flow = flow == "oauth_authorize"
    oauth_discover_flow = flow == "oauth_discover"
    team_oauth_flow = flow == "team_oauth_authorize"
    team_oauth_team_id: int | None = None
    team_oauth_next: str | None = None
    installation_ids: list[str] = []
    if oauth_flow:
        installation_id = state_payload.get("installation_id")
        if not installation_id or not isinstance(installation_id, str):
            return _error("missing_params")
        # Do not require ``current_team`` to match: OAuth completes in a browser
        # session whose active team may differ from the app that started the flow.
        if not Integration.objects.filter(
            kind="github", integration_id=installation_id, team__in=user.teams.all()
        ).exists():
            return _error("invalid_installation")
        installation_ids = [installation_id]
    elif team_oauth_flow:
        # Triggered when the GitHub App is already installed on the org but no PostHog
        # team has captured it (orphan installation). The frontend redirects the user
        # through GitHub's User OAuth so we get a `code` for verify_user_installation_access.
        installation_id = state_payload.get("installation_id")
        team_oauth_team_id = state_payload.get("team_id")
        team_oauth_next = state_payload.get("next") or None
        if not installation_id or not isinstance(installation_id, str):
            return _error("missing_params")
        if not isinstance(team_oauth_team_id, int):
            return _error("invalid_state")
        # Confirm the user still has access to the team they started this flow from.
        if not user.teams.filter(id=team_oauth_team_id).exists():
            return _error("invalid_team")
        installation_ids = [installation_id]
    elif oauth_discover_flow:
        pass
    else:
        installation_id = request.GET.get("installation_id")
        if not installation_id:
            return _error("missing_params")
        installation_ids = [installation_id]

    # Exchange code for user-to-server tokens
    if oauth_flow or oauth_discover_flow or team_oauth_flow:
        authorization = GitHubIntegration.github_user_from_code(code, redirect_uri=github_oauth_redirect_uri())
    else:
        authorization = GitHubIntegration.github_user_from_code(code)
    if authorization is None:
        return _error("exchange_failed")

    if oauth_discover_flow:
        try:
            installation_ids = personal_state.github_user_installation_ids(authorization.access_token)
        except requests.RequestException:
            return _error("installation_fetch_failed")
        if not installation_ids:
            return personal_state.redirect_to_github_app_install(user, connect_from_value)

    for installation_id in installation_ids:
        if not is_valid_github_installation_id(installation_id):
            return _error("invalid_installation_id")

    for installation_id in installation_ids:
        installation_id = str(installation_id)
        # Verify the authorizing user actually has access to this installation.
        # An attacker could use their own OAuth code with someone else's installation_id
        # to obtain an installation token scoped to a different organisation's repos.
        if not oauth_discover_flow:
            try:
                has_access = GitHubIntegration.verify_user_installation_access(
                    installation_id, authorization.access_token
                )
            except requests.RequestException:
                logger.warning(
                    "github_link: installation ownership check failed",
                    installation_id=installation_id,
                    user_id=user.id,
                    exc_info=True,
                )
                return _error("installation_verify_failed")
            if not has_access:
                logger.warning(
                    "github_link: user does not have access to installation",
                    installation_id=installation_id,
                    user_id=user.id,
                )
                return _error("installation_not_authorized")

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
            user,
            GitHubInstallationAccess(
                installation_id=installation_id,
                installation_info=installation_info,
                access_token=installation_access_token,
                token_expires_at=token_expires_at,
                repository_selection=access_token_response.get("repository_selection", "selected"),
            ),
            authorization,
        )

    if team_oauth_flow and team_oauth_team_id is not None:
        installation_id = str(installation_ids[0])
        # Create the team-level Integration that the user originally tried to install.
        # ``integration_from_installation_id`` re-fetches the installation token, so it
        # works whether or not another team in the org has already linked this install.
        try:
            team_integration = GitHubIntegration.integration_from_installation_id(
                installation_id, team_oauth_team_id, user
            )
        except Exception:
            logger.warning(
                "github_link: failed to create team integration",
                installation_id=installation_id,
                team_id=team_oauth_team_id,
                exc_info=True,
            )
            return _error("integration_create_failed")

        # Mirror the fresh-install flow: stamp the connecting user's GitHub login on
        # the team integration card.
        team_integration.config["connecting_user_github_login"] = authorization.gh_login
        team_integration.save(update_fields=["config"])

        target = team_oauth_next or PERSONAL_INTEGRATIONS_SETTINGS_PATH
        forwarded_params: dict[str, str] = {
            "installation_id": installation_id,
            "integration_id": str(team_integration.id),
        }
        joiner = "&" if "?" in target else "?"
        return redirect(f"{target}{joiner}{urlencode(forwarded_params)}")

    return final_github_redirect(connect_from_value)
