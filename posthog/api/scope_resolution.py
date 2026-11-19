from dataclasses import replace
from enum import StrEnum

from django.http import HttpRequest

from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.permissions import get_authenticator_scoped_organization_ids, get_authenticator_scoped_team_ids
from posthog.synthetic_user import SyntheticUser

_SCOPE_RESOLUTION_ATTR = "_posthog_scope_resolution"


class ScopeSource(StrEnum):
    TOKEN = "token"
    CREDENTIAL = "credential"
    USER = "user"


# One request can resolve its scope at several points. The most user-dependent source wins, because the
# question this answers is whether moving the user to another project changes what the request touches.
_SOURCE_PRIORITY = {ScopeSource.TOKEN: 0, ScopeSource.CREDENTIAL: 1, ScopeSource.USER: 2}


@frozen
class ScopeResolution:
    source: ScopeSource
    credential_pins_project: bool
    credential_pins_organization: bool


def note_scope_source(request: Request, source: ScopeSource) -> None:
    http_request: HttpRequest = getattr(request, "_request", request)
    recorded: ScopeResolution | None = getattr(http_request, _SCOPE_RESOLUTION_ATTR, None)
    if recorded is not None and _SOURCE_PRIORITY[recorded.source] >= _SOURCE_PRIORITY[source]:
        return
    resolution = replace(recorded, source=source) if recorded else _resolution_for(request, source)
    setattr(http_request, _SCOPE_RESOLUTION_ATTR, resolution)


def note_user_scope(request: Request) -> None:
    # A project secret API key authenticates as a synthetic user whose team is the key's own project.
    principal: object = request.user
    note_scope_source(request, ScopeSource.CREDENTIAL if isinstance(principal, SyntheticUser) else ScopeSource.USER)


def scope_resolution(request: HttpRequest) -> ScopeResolution | None:
    return getattr(request, _SCOPE_RESOLUTION_ATTR, None)


def _resolution_for(request: Request, source: ScopeSource) -> ScopeResolution:
    principal: object = request.user
    if isinstance(principal, SyntheticUser):
        return ScopeResolution(source=source, credential_pins_project=True, credential_pins_organization=True)
    authenticator = getattr(request, "successful_authenticator", None)
    pins_project = len(get_authenticator_scoped_team_ids(authenticator) or []) == 1
    pins_organization = pins_project or len(get_authenticator_scoped_organization_ids(authenticator) or []) == 1
    return ScopeResolution(
        source=source, credential_pins_project=pins_project, credential_pins_organization=pins_organization
    )
