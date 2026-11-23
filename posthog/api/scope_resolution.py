from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any

from django.http import HttpRequest

import structlog
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.permissions import (
    get_authenticator_scoped_organization_ids,
    get_authenticator_scoped_team_ids,
    get_request_reachable_organization_ids,
)
from posthog.synthetic_user import SyntheticUser

logger = structlog.get_logger(__name__)

CURRENT_ALIAS = "@current"
_SCOPE_RESOLUTION_ATTR = "_posthog_scope_resolution"
_FLAT_ROUTE_ATTR = "_posthog_flat_route"
_TOKEN_ON_PROJECT_PATH_ATTR = "_posthog_token_on_project_path"
_PATH_PROJECT_KWARGS = ("team_id", "project_id")


class ScopeSource(StrEnum):
    TOKEN = "token"
    CREDENTIAL = "credential"
    USER = "user"


@frozen
class ScopeResolution:
    source: ScopeSource
    # Whether the credential reaches exactly one project, or one organization on an organization route.
    credential_pins_scope: bool


def record_scope_resolution(request: Request, *, token_team: Callable[[], Team | None]) -> None:
    """Store on the HttpRequest what decided the request's project, for the usage middleware to read after the view.

    `TeamAndOrgViewSetMixin.initial()` calls this only for requests the middleware reports, so the credential's reach
    is read for those alone. `token_team` is the view's own token lookup, so the source follows the routing precedence.
    """
    # Analytics must never fail the request it observes.
    try:
        resolution = _resolve(request, token_decides=_token_decides(request, token_team))
        setattr(request._request, _SCOPE_RESOLUTION_ATTR, resolution)
    except Exception:
        logger.warning("scope_resolution_record_failed", exc_info=True)


def _token_decides(request: Request, token_team: Callable[[], Team | None]) -> bool:
    return _team_from_token(request, token_team) is not None


def _team_from_token(request: Request, token_team: Callable[[], Team | None]) -> Team | None:
    # The token lookup can parse the request body, so a request that failed authentication skips it.
    if not request.user.is_authenticated:
        return None
    try:
        return token_team()
    except AuthenticationFailed:
        return None


@frozen
class TokenOnProjectPath:
    token_matches_path: bool


def record_token_on_project_path(
    request: Request, *, token_team: Callable[[], Team | None], path_kwargs: Mapping[str, Any]
) -> None:
    """Store on the HttpRequest whether a token decided the project of a route whose path names one."""
    try:
        path_ids = {
            int(value) for name, value in path_kwargs.items() if name in _PATH_PROJECT_KWARGS and str(value).isdigit()
        }
        if not path_ids:
            return
        team = _team_from_token(request, token_team)
        if team is None:
            return
        # An environment route names the team and a project route names the project, and both ids identify the
        # token's own project, so either one counts as a match.
        matches = bool(path_ids & {team.id, team.project_id})
        setattr(request._request, _TOKEN_ON_PROJECT_PATH_ATTR, TokenOnProjectPath(token_matches_path=matches))
    except Exception:
        logger.warning("token_on_project_path_record_failed", exc_info=True)


def token_on_project_path(request: HttpRequest) -> TokenOnProjectPath | None:
    return getattr(request, _TOKEN_ON_PROJECT_PATH_ATTR, None)


def note_flat_route(request: Request) -> None:
    setattr(request._request, _FLAT_ROUTE_ATTR, True)


def is_flat_route(request: HttpRequest) -> bool:
    return getattr(request, _FLAT_ROUTE_ATTR, False)


def scope_resolution(request: HttpRequest) -> ScopeResolution | None:
    return getattr(request, _SCOPE_RESOLUTION_ATTR, None)


def _resolve(request: Request, *, token_decides: bool) -> ScopeResolution:
    principal: object = request.user
    if isinstance(principal, SyntheticUser):
        # A project secret API key signs in as a synthetic user whose team is the key's own project.
        return ScopeResolution(source=ScopeSource.CREDENTIAL, credential_pins_scope=True)

    source = ScopeSource.TOKEN if token_decides else ScopeSource.USER
    if request.path.strip("/").split("/")[1:2] == ["organizations"]:
        reachable_organizations = get_request_reachable_organization_ids(request)
        return ScopeResolution(
            source=source,
            credential_pins_scope=reachable_organizations is not None and len(reachable_organizations) == 1,
        )
    return ScopeResolution(
        source=source, credential_pins_scope=_pins_one_project(getattr(request, "successful_authenticator", None))
    )


def _pins_one_project(authenticator: object) -> bool:
    scoped_teams = get_authenticator_scoped_team_ids(authenticator) or []
    scoped_organizations = get_authenticator_scoped_organization_ids(authenticator)
    if len(scoped_teams) <= 1 or scoped_organizations is None:
        return len(scoped_teams) == 1
    # A key can list projects outside the organizations it is restricted to, and permission checks refuse those.
    reachable_teams = Team.objects.filter(id__in=scoped_teams, organization_id__in=scoped_organizations)
    return len(reachable_teams.values_list("id", flat=True)[:2]) == 1
