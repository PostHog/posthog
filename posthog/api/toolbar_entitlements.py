from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.user import ToolbarEntitlementsSerializer, _toolbar_entitlements, _user_can_access_toolbar
from posthog.models.user import User


@extend_schema(extensions={"x-product": "core"})
class ToolbarEntitlementsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    # The toolbar's OAuth token already holds `user:read`, and `/api/users/@me/` shows the same plan
    # features to that scope. The URL's team still bounds the token, because this route is team-nested.
    scope_object = "user"

    @extend_schema(
        summary="Get toolbar plan entitlements for a project",
        description=(
            "Returns which paid toolbar tools the organization that owns this project can use. "
            "Requires toolbar access to the project."
        ),
        responses={200: ToolbarEntitlementsSerializer},
    )
    @action(detail=False, methods=["get"], url_path="entitlements", required_scopes=["user:read"])
    def entitlements(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not _user_can_access_toolbar(cast(User, request.user), self.team):
            raise PermissionDenied("You don't have access to the toolbar for this project.")

        serializer = ToolbarEntitlementsSerializer({"entitlements": _toolbar_entitlements(self.team.organization)})
        return Response(serializer.data)
