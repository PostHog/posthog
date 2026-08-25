from typing import cast

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import get_authenticator_scoped_organization_ids, get_authenticator_scoped_team_ids


class ScopedTokenPermission(BasePermission):
    """
    Holds a scoped token to its own project and organization.

    `APIScopePermission` skips team and org enforcement for `scope_object = "user"`
    so `/api/users/@me/` can serve any project, but this view is project-nested, so
    the enforcement still has to happen somewhere.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        team = cast(TeamAndOrgViewSetMixin, view).team
        scoped_team_ids = get_authenticator_scoped_team_ids(request.successful_authenticator)
        if scoped_team_ids and team.id not in scoped_team_ids:
            raise PermissionDenied(f"API key does not have access to the requested project: ID {team.id}.")

        scoped_organization_ids = get_authenticator_scoped_organization_ids(request.successful_authenticator)
        if scoped_organization_ids and str(team.organization_id) not in scoped_organization_ids:
            raise PermissionDenied(
                f"API key does not have access to the requested organization: ID {team.organization_id}."
            )

        return True
