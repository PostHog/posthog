"""Team GitHub integration service functions (extracted from IntegrationViewSet)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.utils.crypto import get_random_string

import requests
import structlog
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.api.github_callback import state as github_callback_state
from posthog.api.github_callback.state import github_installation_id_q
from posthog.api.github_callback.types import (
    FlowKind,
    GitHubAuthorizeState,
    connect_from_for_next,
    github_oauth_redirect_uri,
)
from posthog.api.github_callback.validation import is_valid_github_installation_id, validation_error_code
from posthog.models import Organization, Team
from posthog.models.integration import (
    GitHubInstallationAccess,
    GitHubInstallationAccessFetchError,
    GitHubIntegration,
    Integration,
    invalidate_github_repository_caches_for_installation,
)
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration, user_github_integration_from_installation
from posthog.utils import is_relative_url

logger = structlog.get_logger(__name__)

GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION = "github_link_existing_orphan_installation"
GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED = "github_link_existing_personal_github_required"
PERSONAL_GITHUB_REQUIRED_MESSAGE = (
    "You must connect your personal GitHub account (via Linked Accounts) before linking an existing "
    "installation, to confirm you have access to the GitHub App installation."
)


@dataclass(frozen=True)
class TeamGitHubFinishSetupResult:
    next_url: str
    installation_id: str
    integration: Integration | None = None
    oauth_url: str | None = None


def installation_token_expires_at(integration: Integration) -> str:
    refreshed_at = integration.config.get("refreshed_at", 0)
    expires_in = integration.config.get("expires_in", 3600)
    return datetime.fromtimestamp(refreshed_at + expires_in, tz=UTC).isoformat()


def create_team_github_integration_from_oauth_code(
    *,
    request: Request,
    user: User,
    team_id: int,
    installation_id: str | None,
    state_token: str | None,
    code: str | None,
) -> Integration:
    if not installation_id:
        raise ValidationError("An installation_id must be provided")

    if not state_token:
        raise ValidationError("A state token must be provided")

    if not code:
        raise ValidationError("An OAuth code must be provided")

    github_callback_state.consume_github_authorize_state(request, state_token)

    authorization = GitHubIntegration.github_user_from_code(code)
    if authorization is None:
        raise ValidationError("Failed to exchange the OAuth code — ensure GITHUB_APP_CLIENT_SECRET is configured")

    if not is_valid_github_installation_id(installation_id):
        raise ValidationError("Invalid installation_id")
    try:
        has_access = GitHubIntegration.verify_user_installation_access(installation_id, authorization.access_token)
    except requests.RequestException:
        logger.warning(
            "github_integration_create: installation ownership check failed",
            installation_id=installation_id,
            user_id=user.id,
            exc_info=True,
        )
        raise ValidationError("Failed to verify installation access")
    if not has_access:
        logger.warning(
            "github_integration_create: user does not have access to installation",
            installation_id=installation_id,
            user_id=user.id,
        )
        raise ValidationError("You do not have access to this GitHub installation")

    instance = GitHubIntegration.integration_from_installation_id(installation_id, team_id, user)

    instance.config["connecting_user_github_login"] = authorization.gh_login
    instance.save(update_fields=["config"])
    user_github_integration_from_installation(
        user,
        GitHubInstallationAccess(
            installation_id=installation_id,
            installation_info=instance.config,
            access_token=instance.sensitive_config.get("access_token", ""),
            token_expires_at=installation_token_expires_at(instance),
            repository_selection=instance.config.get("repository_selection", "selected"),
        ),
        authorization,
        create_only=True,
    )

    return instance


def execute_team_github_finish_setup(
    *,
    user: User,
    team: Team,
    request: Request,
    installation_id: str,
    code: str | None,
    setup_action: str,
    state_raw: str | None,
) -> TeamGitHubFinishSetupResult:
    if not is_valid_github_installation_id(installation_id):
        raise ValidationError("Invalid installation_id")

    installation_id_str = str(installation_id)

    if setup_action == "update":
        existing = github_callback_state.github_integration_for_installation(team.id, installation_id_str)
        if existing is not None:
            _, next_url, _ = github_callback_state.consume_github_authorize_state(
                request, state_raw, setup_action="update", code=None
            )
            refreshed = refresh_team_github_integration(
                user,
                team.id,
                installation_id_str,
                existing=existing,
            )
            return TeamGitHubFinishSetupResult(
                next_url=next_url,
                installation_id=installation_id_str,
                integration=refreshed,
            )

    _state_token, next_url, _team_id = github_callback_state.consume_github_authorize_state(
        request, state_raw, setup_action=setup_action, code=code
    )

    is_already_installed = setup_action == "update" or not code
    connect_from = connect_from_for_next(next_url)

    if is_already_installed:
        try:
            integration = link_existing_team_github_integration(
                user=user,
                organization=team.organization,
                team_id=team.id,
                source_team_id=None,
                installation_id_param=installation_id_str,
            )
        except ValidationError as exc:
            error_code = validation_error_code(exc)
            if error_code not in (
                GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION,
                GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
            ):
                raise
            oauth_url = build_team_github_oauth_authorize_url(
                user_id=user.id,
                team_id=team.id,
                installation_id=installation_id_str,
                next_url=next_url,
                connect_from=connect_from,
            )
            return TeamGitHubFinishSetupResult(
                next_url=next_url,
                installation_id=installation_id_str,
                oauth_url=oauth_url,
            )

        return TeamGitHubFinishSetupResult(
            next_url=next_url,
            installation_id=installation_id_str,
            integration=integration,
        )

    fresh_token = os.urandom(33).hex()
    github_callback_state.store_github_authorize_state(
        github_callback_state.authenticated_user_id(request),
        fresh_token,
        next_url,
        team.id,
    )
    integration = create_team_github_integration_from_oauth_code(
        request=request,
        user=user,
        team_id=team.id,
        installation_id=installation_id_str,
        state_token=fresh_token,
        code=code,
    )
    return TeamGitHubFinishSetupResult(
        next_url=next_url,
        installation_id=installation_id_str,
        integration=integration,
    )


def refresh_team_github_integration(
    user: User,
    team_id: int,
    installation_id: str,
    *,
    existing: Integration,
) -> Integration:
    try:
        return GitHubIntegration.integration_from_installation_id(installation_id, team_id, user)
    except GitHubInstallationAccessFetchError:
        logger.warning(
            "github_team_setup: failed to refresh integration after update",
            installation_id=installation_id,
            user_id=user.id,
            team_id=team_id,
            exc_info=True,
        )
        invalidate_github_repository_caches_for_installation(installation_id)
        return existing


def prepare_team_github_manage_callback(*, user_id: int, next_url: str, team_id: int) -> None:
    if next_url and not is_relative_url(next_url):
        raise ValidationError("next must be a relative path starting with /")
    token = os.urandom(33).hex()
    github_callback_state.store_github_authorize_state(
        user_id,
        token,
        next_url,
        team_id,
        flow=FlowKind.TEAM_UPDATE,
    )


def link_existing_team_github_integration(
    *,
    user: User,
    organization: Organization,
    team_id: int,
    source_team_id: Any | None,
    installation_id_param: Any | None,
) -> Integration:
    if installation_id_param and not is_valid_github_installation_id(installation_id_param):
        raise ValidationError("Invalid installation_id")

    installation_id_match = github_installation_id_q(installation_id_param) if installation_id_param else None

    if source_team_id:
        try:
            source_team_id_int = int(source_team_id)
        except (TypeError, ValueError):
            raise ValidationError("source_team_id must be an integer")

        if not organization.teams.filter(id=source_team_id_int).exists():
            raise ValidationError("Source team not found in your organization")

        qs = Integration.objects.filter(team_id=source_team_id_int, kind="github")
        if installation_id_match is not None:
            qs = qs.filter(installation_id_match)

        source = qs.order_by("id").first()
        if source is None:
            raise ValidationError("Source team does not have a GitHub integration")
    elif installation_id_param:
        existing = (
            Integration.objects.filter(
                team__organization_id=organization.id,
                kind="github",
            )
            .filter(installation_id_match)
            .order_by("id")
            .first()
        )
        if existing is None:
            raise ValidationError(
                "No team in your organization has this GitHub installation linked",
                code=GITHUB_LINK_EXISTING_ERROR_ORPHAN_INSTALLATION,
            )
        source = existing
    else:
        raise ValidationError("source_team_id or installation_id is required")

    installation_id = (source.config or {}).get("installation_id")
    if not installation_id:
        raise ValidationError("Source integration is missing installation_id")

    user_github_integration = UserIntegration.objects.filter(user=user, kind="github").order_by("-created_at").first()
    user_access_token = (
        user_github_integration.sensitive_config.get("access_token") if user_github_integration else None
    )
    if not user_access_token:
        raise ValidationError(
            PERSONAL_GITHUB_REQUIRED_MESSAGE,
            code=GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
        )
    try:
        has_access = GitHubIntegration.verify_user_installation_access(str(installation_id), user_access_token)
    except requests.RequestException:
        raise ValidationError("Failed to verify installation access")
    if not has_access:
        raise ValidationError(
            PERSONAL_GITHUB_REQUIRED_MESSAGE,
            code=GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
        )

    instance = GitHubIntegration.integration_from_installation_id(str(installation_id), team_id, user)

    source_login = (source.config or {}).get("connecting_user_github_login")
    if source_login and not (instance.config or {}).get("connecting_user_github_login"):
        instance.config["connecting_user_github_login"] = source_login
        instance.save(update_fields=["config"])

    return instance


def build_team_github_oauth_authorize_url(
    *,
    user_id: int,
    team_id: int,
    installation_id: str,
    next_url: str,
    connect_from: str | None,
) -> str:
    if not installation_id:
        raise ValidationError("installation_id is required")

    if not is_valid_github_installation_id(installation_id):
        raise ValidationError("Invalid installation_id")

    if next_url and not is_relative_url(next_url):
        raise ValidationError("next must be a relative path starting with /")

    client_id = settings.GITHUB_APP_CLIENT_ID
    if not client_id:
        raise ValidationError("GitHub App client ID is not configured")

    token = get_random_string(48)
    resolved_connect_from = connect_from if connect_from == "posthog_code" else connect_from_for_next(next_url)
    authorize_state = GitHubAuthorizeState(
        token=token,
        flow=FlowKind.TEAM_OAUTH,
        user_id=user_id,
        team_id=team_id,
        installation_id=str(installation_id),
        next_url=next_url or None,
        connect_from=resolved_connect_from,
    )
    github_callback_state.store_personal_authorize_state(authorize_state)

    return "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": github_oauth_redirect_uri(),
            "state": urlencode({"token": token}),
        }
    )
