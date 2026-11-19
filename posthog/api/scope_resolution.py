from enum import StrEnum

from django.http import HttpRequest

import structlog
from rest_framework.request import Request

from posthog.api.utils import get_token
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


class ScopeSource(StrEnum):
    TOKEN = "token"
    CREDENTIAL = "credential"
    USER = "user"


@frozen
class ScopeResolution:
    source: ScopeSource
    # Whether the credential reaches exactly one project, or one organization on an organization route.
    credential_pins_scope: bool


def record_scope_resolution(request: Request, *, flat_route: bool) -> None:
    """Store on the HttpRequest what decided the request's project, for the usage middleware to read after the view.

    `TeamAndOrgViewSetMixin.initial()` calls this only for requests the middleware reports, so the credential's reach
    is read for those alone.
    """
    # Analytics must never fail the request it observes.
    try:
        # A query token picks the project on a flat route; on an @current route the alias wins over it. get_token can
        # parse the body, so a request that failed authentication skips it.
        token_decides = flat_route and request.user.is_authenticated and bool(get_token(None, request))
        setattr(request._request, _SCOPE_RESOLUTION_ATTR, _resolve(request, token_decides=token_decides))
    except Exception:
        logger.warning("scope_resolution_record_failed", exc_info=True)


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
