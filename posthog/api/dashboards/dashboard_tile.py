from typing import cast

from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.dashboards.basic_dashboard_tile_serializer import BasicDashboardTileSerializer
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import DashboardTile, User
from posthog.models.utils import UUIDT
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class DashboardTileViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    serializer_class = BasicDashboardTileSerializer
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]

    def get_queryset(self):
        return DashboardTile.objects.select_related("dashboard", "insight", "dashboard__team", "insight__team")

    def create(self, request: Request, *args, **kwargs) -> Response:
        tile_serializer = BasicDashboardTileSerializer(
            data=request.data,
            context={
                "user": cast(User, request.user),
                "team": self.team,
                "organization_id": UUIDT(uuid_str=self.organization_id),
            },
        )
        tile_serializer.is_valid(raise_exception=True)
        tile = tile_serializer.save()

        serializer = BasicDashboardTileSerializer(tile, context={"request": request})
        return Response(data=serializer.data, status=status.HTTP_200_OK)
