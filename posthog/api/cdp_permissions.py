from typing import TYPE_CHECKING, cast

from rest_framework.permissions import SAFE_METHODS, BasePermission

from products.access_control.backend.facade import api as access_control_api

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView

    from posthog.api.routing import TeamAndOrgViewSetMixin
    from posthog.models import User


class CDPPropertyAccessPermission(BasePermission):
    message = (
        "Your property access permissions do not allow configuring pipelines, running them, or reading their logs. "
        "Ask a project administrator for help."
    )
    sensitive_read_actions = frozenset(
        {"logs", "invocation_results", "invocation_results_count", "invocation_result", "assets", "asset_content"}
    )

    def has_permission(self, request: "Request", view: "APIView") -> bool:
        team_view = cast("TeamAndOrgViewSetMixin", view)
        if request.method in SAFE_METHODS and team_view.action not in self.sensitive_read_actions:
            return True

        return not access_control_api.get_restricted_properties_with_group_type_index_for_team(
            team_id=team_view.team_id, user=cast("User", request.user)
        )


class CDPLogPropertyAccessPermission(CDPPropertyAccessPermission):
    sensitive_read_actions = frozenset({"list", "retrieve"})


class CDPOrganizationPropertyAccessPermission(CDPPropertyAccessPermission):
    def has_permission(self, request: "Request", view: "APIView") -> bool:
        if request.method in SAFE_METHODS:
            return True

        org_view = cast("TeamAndOrgViewSetMixin", view)
        return not access_control_api.has_restricted_properties_in_organization(
            organization_id=org_view.organization.id, user=cast("User", request.user)
        )
