"""Team-level GitHub App setup finish logic."""

from __future__ import annotations

from typing import Any, cast

from django.http import HttpRequest

import structlog
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.api.github_callback import redirects, state
from posthog.api.github_callback.team_services import execute_team_github_finish_setup, refresh_team_github_integration
from posthog.api.github_callback.types import FinishResult, github_oauth_callback_error_code
from posthog.api.github_callback.validation import is_valid_github_installation_id, validation_error_code
from posthog.auth import SessionAuthentication
from posthog.models import OrganizationMembership, Team, User
from posthog.models.integration import Integration
from posthog.user_permissions import UserPermissions

logger = structlog.get_logger(__name__)


def validation_error_message(exc: ValidationError) -> str:
    detail: object = exc.detail
    if isinstance(detail, list) and detail:
        return str(detail[0])
    if isinstance(detail, dict):
        for value in detail.values():
            if isinstance(value, list) and value:
                return str(value[0])
            return str(value)
    return str(detail)


def authenticated_drf_request(http_request: HttpRequest) -> Request:
    drf_request = Request(http_request)
    auth_result = SessionAuthentication().authenticate(drf_request)
    if auth_result is not None:
        drf_request.user, drf_request.auth = auth_result
    elif http_request.user.is_authenticated:
        mutable_request = cast(Any, drf_request)
        mutable_request._user = http_request.user
        mutable_request._auth = None
    return cast(Request, drf_request)


def user_is_team_admin(user: User, team: Team | int) -> bool:
    if isinstance(team, int):
        try:
            team = Team.objects.get(id=team)
        except Team.DoesNotExist:
            return False
    level = UserPermissions(user).team(team).effective_membership_level
    return level is not None and level >= OrganizationMembership.Level.ADMIN


def finish_team_setup_update(http_request, existing: Integration) -> FinishResult:
    """Refresh a team Integration after GitHub installation settings change without cached state."""
    user = cast(User, http_request.user)
    installation_id = http_request.GET.get("installation_id")

    if not is_valid_github_installation_id(installation_id):
        return FinishResult(
            redirect_kind="team_setup",
            next_url=None,
            team_id=None,
            error="invalid_installation_id",
        )

    installation_id_str = str(installation_id)
    team_id = existing.team_id
    if not user_is_team_admin(user, team_id):
        return FinishResult(
            redirect_kind="team_setup",
            next_url=redirects.landing_url(None, team_id),
            team_id=team_id,
            error="invalid_team",
        )

    refreshed = refresh_team_github_integration(user, team_id, installation_id_str, existing=existing)

    return FinishResult(
        redirect_kind="team_setup",
        next_url=redirects.landing_url(None, team_id),
        team_id=team_id,
        installation_id=installation_id_str,
        integration_id=str(refreshed.id),
    )


def finish_team_setup(http_request) -> FinishResult:
    state_raw = http_request.GET.get("state")
    user = cast(User, http_request.user)
    installation_id = http_request.GET.get("installation_id")
    team_id, next_url = state.resolve_github_setup_callback_context(user, state_raw)

    if github_error := http_request.GET.get("error"):
        logger.warning(
            "github_team_setup: GitHub returned error on callback",
            error=github_error,
            description=http_request.GET.get("error_description"),
            user_id=user.id,
        )
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            error=github_oauth_callback_error_code(github_error),
        )

    if not installation_id:
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            pending=True,
        )

    if team_id is None:
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            error="invalid_state",
        )

    try:
        team = Team.objects.select_related("organization").get(id=team_id)
    except Team.DoesNotExist:
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            error="invalid_team",
        )

    if not user_is_team_admin(user, team):
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            error="invalid_team",
        )

    setup_action = http_request.GET.get("setup_action") or ""
    code = http_request.GET.get("code") or None

    request = authenticated_drf_request(http_request)

    try:
        result = execute_team_github_finish_setup(
            user=user,
            team=team,
            request=request,
            installation_id=str(installation_id),
            code=code,
            setup_action=setup_action,
            state_raw=state_raw,
        )
    except ValidationError as exc:
        error_code = validation_error_code(exc) or "github_install_failed"
        detail = validation_error_message(exc)
        logger.warning(
            "github_team_setup: finish setup failed",
            error_code=error_code,
            user_id=user.id,
            team_id=team_id,
        )
        return FinishResult(
            redirect_kind="team_setup",
            next_url=next_url,
            team_id=team_id,
            error=error_code,
            error_message=detail,
        )

    if result.oauth_url:
        return FinishResult(redirect_kind="oauth_url", oauth_url=result.oauth_url)

    success_next = str(result.next_url or redirects.landing_url(next_url, team_id))
    integration_id = str(result.integration.id) if result.integration is not None else None
    return FinishResult(
        redirect_kind="team_setup",
        next_url=success_next,
        team_id=team_id,
        installation_id=str(result.installation_id or installation_id),
        integration_id=integration_id,
    )
