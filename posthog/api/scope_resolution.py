from enum import StrEnum

from django.http import HttpRequest

import structlog
from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.permissions import get_authenticator_scoped_team_ids, get_request_reachable_organization_ids
from posthog.synthetic_user import SyntheticUser

logger = structlog.get_logger(__name__)

CURRENT_ALIAS = "@current"
_SCOPE_RESOLUTION_ATTR = "_posthog_scope_resolution"


class ScopeSource(StrEnum):
    TOKEN = "token"
    CREDENTIAL = "credential"
    USER = "user"


@frozen
class ScopeResolution:
    source: ScopeSource
    credential_pins_project: bool
    credential_pins_organization: bool


def record_scope_resolution(request: Request, *, token_decides: bool) -> None:
    """Store on the HttpRequest what decided the request's project, for the usage middleware to read after the view.

    `TeamAndOrgViewSetMixin.initial()` calls this only for requests the middleware reports, so the credential's reach
    is read for those alone.
    """
    # Analytics must never fail the request it observes.
    try:
        setattr(request._request, _SCOPE_RESOLUTION_ATTR, _resolve(request, token_decides=token_decides))
    except Exception:
        logger.warning("scope_resolution_record_failed", exc_info=True)


def scope_resolution(request: HttpRequest) -> ScopeResolution | None:
    return getattr(request, _SCOPE_RESOLUTION_ATTR, None)


def _resolve(request: Request, *, token_decides: bool) -> ScopeResolution:
    principal: object = request.user
    if isinstance(principal, SyntheticUser):
        # A project secret API key signs in as a synthetic user whose team is the key's own project.
        return ScopeResolution(
            source=ScopeSource.CREDENTIAL, credential_pins_project=True, credential_pins_organization=True
        )

    scoped_teams = get_authenticator_scoped_team_ids(getattr(request, "successful_authenticator", None)) or []
    reachable_organizations = get_request_reachable_organization_ids(request)
    return ScopeResolution(
        source=ScopeSource.TOKEN if token_decides else ScopeSource.USER,
        credential_pins_project=len(scoped_teams) == 1,
        credential_pins_organization=reachable_organizations is not None and len(reachable_organizations) == 1,
    )
