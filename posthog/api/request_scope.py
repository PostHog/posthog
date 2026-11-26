from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.http import HttpRequest

import structlog
from rest_framework.exceptions import APIException
from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.synthetic_user import SyntheticUser

logger = structlog.get_logger(__name__)

_REQUEST_SCOPE_SHADOW_ATTR = "_posthog_request_scope_shadow"


class ScopeLevel(StrEnum):
    TEAM = "team"
    PROJECT = "project"
    ORGANIZATION = "organization"


class RequestScopeSource(StrEnum):
    PATH = "path"
    TOKEN = "token"
    SECRET_KEY = "secret_key"


class ShadowOutcome(StrEnum):
    SAME = "same"
    DIFFERENT = "different"
    UNPLACED = "unplaced"


@frozen
class RequestScope:
    source: RequestScopeSource
    scope_id: str


@frozen
class RequestScopeShadow:
    level: ScopeLevel
    source: RequestScopeSource | None
    outcome: ShadowOutcome
    # The id the view uses today, which is the id an explicit request should name.
    current_scope_id: str


_PATH_KWARG_BY_LEVEL = {
    ScopeLevel.TEAM: "team_id",
    ScopeLevel.PROJECT: "project_id",
    ScopeLevel.ORGANIZATION: "organization_id",
}


def resolve_request_scope(
    level: ScopeLevel,
    *,
    path_kwargs: Mapping[str, Any],
    token_team: Callable[[], Team | None] | None,
    secret_key_team: Team | None,
) -> RequestScope | None:
    """Find the scope a request names, never reading the user it signs in as.

    The order is the id in the path, then a project token on views that accept one, then a project secret API key.
    `token_team` is None on views that don't accept a token.
    """
    path_id = _path_id(level, path_kwargs.get(_PATH_KWARG_BY_LEVEL[level]))
    if path_id is not None:
        return RequestScope(source=RequestScopeSource.PATH, scope_id=path_id)

    team_from_token = token_team() if token_team is not None else None
    if team_from_token is not None:
        return RequestScope(source=RequestScopeSource.TOKEN, scope_id=_team_scope_id(level, team_from_token))

    if secret_key_team is not None:
        return RequestScope(source=RequestScopeSource.SECRET_KEY, scope_id=_team_scope_id(level, secret_key_team))

    return None


def _path_id(level: ScopeLevel, value: Any) -> str | None:
    # Parse the way parents_query_dict does, so "@current" and other names that are not ids place nothing.
    try:
        if level == ScopeLevel.ORGANIZATION:
            return str(UUID(str(value)))
        return str(int(value))
    except (TypeError, ValueError):
        return None


def _team_scope_id(level: ScopeLevel, team: Team) -> str:
    if level == ScopeLevel.ORGANIZATION:
        return str(team.organization_id)
    if level == ScopeLevel.PROJECT:
        return str(team.project_id)
    return str(team.id)


def record_request_scope_shadow(
    request: Request,
    *,
    level: ScopeLevel,
    path_kwargs: Mapping[str, Any],
    token_team: Callable[[], Team | None] | None,
    current_scope_id: Callable[[], Any],
) -> None:
    """Store on the HttpRequest how the request-only resolver compares with the scope the view uses today.

    It changes nothing about the request. `current_scope_id` reads the view's own resolution, so the view calls this
    only once its checks pass, and a request whose view can't resolve a scope records nothing.
    """
    try:
        if not request.user.is_authenticated:
            return
        principal: object = request.user
        secret_key_team = principal.team if isinstance(principal, SyntheticUser) else None
        resolved = resolve_request_scope(
            level, path_kwargs=path_kwargs, token_team=token_team, secret_key_team=secret_key_team
        )
        current = str(current_scope_id())
    except APIException:
        return
    except Exception:
        logger.warning("request_scope_shadow_failed", exc_info=True)
        return

    if resolved is None:
        shadow = RequestScopeShadow(level=level, source=None, outcome=ShadowOutcome.UNPLACED, current_scope_id=current)
    else:
        outcome = ShadowOutcome.SAME if resolved.scope_id == current else ShadowOutcome.DIFFERENT
        shadow = RequestScopeShadow(level=level, source=resolved.source, outcome=outcome, current_scope_id=current)
    setattr(request._request, _REQUEST_SCOPE_SHADOW_ATTR, shadow)


def request_scope_shadow(request: HttpRequest) -> RequestScopeShadow | None:
    return getattr(request, _REQUEST_SCOPE_SHADOW_ATTR, None)
