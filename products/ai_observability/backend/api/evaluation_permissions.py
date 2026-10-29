from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rest_framework.permissions import BasePermission

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView

    from posthog.api.routing import TeamAndOrgViewSetMixin
    from posthog.models import User


class EvaluationSourceAccessPermission(BasePermission):
    message = "Access to all event properties is required to access evaluations and reports."

    def has_permission(self, request: Request, view: APIView) -> bool:
        restrictions = get_restricted_properties_with_group_type_index_for_team(
            user=cast("User", request.user), team_id=cast("TeamAndOrgViewSetMixin", view).team_id
        )
        return not split_restricted_property_names(restrictions).event
