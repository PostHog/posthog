"""Team-level GitHub App setup callback (GitHub Setup URL redirect handler)."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import parse_qsl, quote, urlencode, urlparse

from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

import structlog
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.api.integration import (
    IntegrationViewSet,
    _execute_github_finish_setup,
    _github_finish_setup_error_code,
    _resolve_github_setup_callback_context,
    _validation_error_message,
    github_integrations_settings_path,
    github_oauth_callback_error_code,
)
from posthog.api.user_integration import ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH, is_personal_github_setup_state
from posthog.auth import SessionAuthentication
from posthog.models import OrganizationMembership, Team, User
from posthog.user_permissions import UserPermissions
from posthog.utils import is_relative_url

logger = structlog.get_logger(__name__)


def _authenticated_drf_request(http_request: HttpRequest) -> Request:
    """Wrap a session-authenticated Django request for DRF viewset calls."""
    drf_request = Request(http_request)
    auth_result = SessionAuthentication().authenticate(drf_request)
    if auth_result is not None:
        drf_request.user, drf_request.auth = auth_result
    elif http_request.user.is_authenticated:
        mutable_request = cast(Any, drf_request)
        mutable_request._user = http_request.user
        mutable_request._auth = None
    return cast(Request, drf_request)


def _user_is_team_admin(user: User, team_id: int) -> bool:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return False
    level = UserPermissions(user).team(team).effective_membership_level
    return level is not None and level >= OrganizationMembership.Level.ADMIN


def _append_query_params(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    parsed = urlparse(url)
    merged = dict(parse_qsl(parsed.query))
    merged.update(params)
    query = urlencode(merged)
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{parsed.path}{('?' + query) if query else ''}{fragment}"


def _landing_url(next_url: str | None, team_id: int | None) -> str:
    if next_url and is_relative_url(next_url):
        return next_url
    if team_id is not None:
        return github_integrations_settings_path(team_id)
    return "/settings/environment-integrations"


def _team_github_setup_redirect(
    *,
    next_url: str | None,
    team_id: int | None,
    error: str | None = None,
    error_message: str | None = None,
    installation_id: str | None = None,
    integration_id: str | None = None,
    pending: bool = False,
) -> HttpResponseRedirect:
    target = _landing_url(next_url, team_id)
    params: dict[str, str] = {}

    if pending:
        params["github_install_pending"] = "1"

    if error:
        if ACCOUNT_CONNECTED_GITHUB_INTEGRATION_PATH in target:
            params["error"] = error
        else:
            params["github_setup_error"] = error
        if error_message:
            params["error_message"] = error_message
    else:
        if installation_id:
            params["installation_id"] = installation_id
        if integration_id:
            params["integration_id"] = integration_id

    return redirect(_append_query_params(target, params))


def _integration_viewset_for_team(http_request: HttpRequest, team_id: int) -> IntegrationViewSet:
    drf_request = _authenticated_drf_request(http_request)
    viewset = IntegrationViewSet()
    viewset.action = "create"
    viewset.request = drf_request
    viewset.kwargs = {"parent_lookup_team_id": team_id}
    viewset.format_kwarg = None
    return viewset


@require_http_methods(["GET"])
def github_team_integration_complete(request: HttpRequest) -> HttpResponseRedirect:
    """Complete GitHub App setup from GitHub's Setup URL redirect.

    Team-level installs finish here. Personal UserIntegration installs use the same
    GitHub App Setup URL but carry ``source=user_integration`` in ``state`` and are
    forwarded to ``/complete/github-link/``.
    """
    state_raw = request.GET.get("state")
    if is_personal_github_setup_state(state_raw):
        callback_url = request.get_full_path().replace("/integrations/github/callback", "/complete/github-link", 1)
        if not request.user.is_authenticated:
            return redirect(f"/login?next={quote(callback_url)}")
        return redirect(callback_url)

    if not request.user.is_authenticated:
        return redirect(f"/login?next={quote(request.get_full_path(), safe='')}")

    user = cast(User, request.user)
    installation_id = request.GET.get("installation_id")
    team_id, next_url = _resolve_github_setup_callback_context(user, state_raw)

    if github_error := request.GET.get("error"):
        logger.warning(
            "github_team_setup: GitHub returned error on callback",
            error=github_error,
            description=request.GET.get("error_description"),
            user_id=user.id,
        )
        return _team_github_setup_redirect(
            next_url=next_url,
            team_id=team_id,
            error=github_oauth_callback_error_code(github_error),
        )

    if not installation_id:
        return _team_github_setup_redirect(
            next_url=next_url,
            team_id=team_id,
            pending=True,
        )

    if team_id is None:
        return _team_github_setup_redirect(
            next_url=next_url,
            team_id=team_id,
            error="invalid_state",
        )

    if not _user_is_team_admin(user, team_id):
        return _team_github_setup_redirect(
            next_url=next_url,
            team_id=team_id,
            error="invalid_team",
        )

    setup_action = request.GET.get("setup_action") or ""
    code = request.GET.get("code") or None

    viewset = _integration_viewset_for_team(request, team_id)

    try:
        result = _execute_github_finish_setup(
            viewset,
            viewset.request,
            installation_id=str(installation_id),
            code=code,
            setup_action=setup_action,
            state_raw=state_raw,
        )
    except ValidationError as exc:
        error_code = _github_finish_setup_error_code(exc) or "github_install_failed"
        detail = _validation_error_message(exc)
        logger.warning(
            "github_team_setup: finish setup failed",
            error_code=error_code,
            user_id=user.id,
            team_id=team_id,
        )
        return _team_github_setup_redirect(
            next_url=next_url,
            team_id=team_id,
            error=error_code,
            error_message=detail,
        )

    oauth_url = result.get("oauth_url")
    if oauth_url:
        return redirect(str(oauth_url))

    success_next = str(result.get("next") or _landing_url(next_url, team_id))
    integration = result.get("integration") or {}
    integration_id = integration.get("id")
    return _team_github_setup_redirect(
        next_url=success_next,
        team_id=team_id,
        installation_id=str(result.get("installation_id") or installation_id),
        integration_id=str(integration_id) if integration_id is not None else None,
    )
