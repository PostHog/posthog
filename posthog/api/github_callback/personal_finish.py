from typing import cast

from django.http import HttpRequest

import requests
import structlog

from posthog.api.github_callback import personal_state, router, state
from posthog.api.github_callback.types import FinishResult, FlowKind, is_valid_github_installation_id
from posthog.models import User
from posthog.models.integration import GitHubInstallationAccessFetchError, GitHubIntegration, Integration
from posthog.models.user_integration import (
    UserIntegration,
    refresh_user_github_installation_access,
    user_github_integration_from_installation,
)

logger = structlog.get_logger(__name__)


def finish_personal(request: HttpRequest) -> FinishResult:
    """Complete personal GitHub App install or OAuth flows."""
    user = cast(User, request.user)
    connect_from_value: str | None = None

    def _error(reason: str) -> FinishResult:
        logger.warning("github_link: redirecting with error", reason=reason, user_id=user.id)
        return FinishResult(redirect_kind="personal_finish", connect_from=connect_from_value, error=reason)

    if github_error := request.GET.get("error"):
        logger.warning(
            "github_link: GitHub returned error on callback",
            error=github_error,
            description=request.GET.get("error_description"),
            user_id=user.id,
        )
        connect_from_value = personal_state.app_connect_from_from_state_query(request)
        return _error(github_error if github_error == "access_denied" else "github_oauth_error")

    code = request.GET.get("code")
    state_raw = request.GET.get("state")

    if not code or not state_raw:
        return _error("missing_params")

    token = personal_state.github_state_token(state_raw)
    authorize_state = state.consume_authorize_state(token, user_id=user.id)
    if authorize_state is None:
        return _error("invalid_state")

    connect_from_value = authorize_state.connect_from
    flow = authorize_state.flow
    oauth_flow = flow == FlowKind.PERSONAL_OAUTH
    oauth_discover_flow = flow == FlowKind.OAUTH_DISCOVER
    team_oauth_flow = flow == FlowKind.TEAM_OAUTH
    team_oauth_team_id = authorize_state.team_id
    team_oauth_next = authorize_state.next_url
    installation_ids: list[str] = []

    if oauth_flow:
        installation_id = authorize_state.installation_id
        if not installation_id:
            return _error("missing_params")
        if not Integration.objects.filter(
            kind="github", integration_id=installation_id, team__in=user.teams.all()
        ).exists():
            return _error("invalid_installation")
        installation_ids = [installation_id]
    elif team_oauth_flow:
        installation_id = authorize_state.installation_id
        if not installation_id:
            return _error("missing_params")
        if team_oauth_team_id is None:
            return _error("invalid_state")
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

    use_oauth_redirect = oauth_flow or oauth_discover_flow or team_oauth_flow
    authorization = router.exchange_user_authorization(code, use_oauth_redirect_uri=use_oauth_redirect)
    if authorization is None:
        return _error("exchange_failed")

    if oauth_discover_flow:
        try:
            installation_ids = personal_state.github_user_installation_ids(authorization.access_token)
        except requests.RequestException:
            return _error("installation_fetch_failed")
        if not installation_ids:
            redirect = personal_state.redirect_to_github_app_install(user, connect_from_value)
            return FinishResult(redirect_kind="oauth_url", oauth_url=redirect.url)

    for installation_id in installation_ids:
        if not is_valid_github_installation_id(installation_id):
            return _error("invalid_installation_id")

    for installation_id in installation_ids:
        installation_id = str(installation_id)
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

        try:
            installation_access = GitHubIntegration.fetch_installation_access(installation_id)
        except GitHubInstallationAccessFetchError as exc:
            if exc.code == "installation_fetch_failed":
                logger.warning("github_link: failed to fetch installation info", exc_info=True)
            return _error(exc.code)

        user_github_integration_from_installation(user, installation_access, authorization)

    if team_oauth_flow and team_oauth_team_id is not None:
        installation_id = str(installation_ids[0])
        try:
            team_integration = GitHubIntegration.integration_from_installation_id(
                installation_id, team_oauth_team_id, user
            )
        except (GitHubInstallationAccessFetchError, requests.RequestException):
            logger.warning(
                "github_link: failed to create team integration",
                installation_id=installation_id,
                team_id=team_oauth_team_id,
                exc_info=True,
            )
            return _error("integration_create_failed")

        team_integration.config["connecting_user_github_login"] = authorization.gh_login
        team_integration.save(update_fields=["config"])

        return FinishResult(
            redirect_kind="team_oauth_success",
            next_url=team_oauth_next,
            installation_id=installation_id,
            integration_id=str(team_integration.id),
        )

    return FinishResult(redirect_kind="personal_finish", connect_from=connect_from_value)


def finish_personal_setup_update(request: HttpRequest) -> FinishResult:
    """Refresh a personal UserIntegration after GitHub installation settings change."""
    user = cast(User, request.user)
    installation_id = request.GET.get("installation_id")

    def _error(reason: str) -> FinishResult:
        logger.warning("github_link: personal setup update failed", reason=reason, user_id=user.id)
        return FinishResult(redirect_kind="personal_finish", connect_from=None, error=reason)

    if not is_valid_github_installation_id(installation_id):
        return _error("invalid_installation_id")

    installation_id = str(installation_id)
    try:
        integration = UserIntegration.objects.get(
            user=user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id=installation_id,
        )
    except UserIntegration.DoesNotExist:
        return _error("invalid_installation")

    try:
        installation_access = GitHubIntegration.fetch_installation_access(installation_id)
    except GitHubInstallationAccessFetchError as exc:
        if exc.code == "installation_fetch_failed":
            logger.warning(
                "github_link: failed to refresh installation after update",
                installation_id=installation_id,
                user_id=user.id,
                exc_info=True,
            )
        return _error(exc.code)

    refresh_user_github_installation_access(integration, installation_access)

    return FinishResult(redirect_kind="personal_finish", connect_from=None)
