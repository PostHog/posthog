from typing import cast

from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.dashboards.basic_dashboard_tile_serializer import BasicDashboardTileSerializer
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.insight import log_insight_activity
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import Dashboard, DashboardTile, Insight, User
from posthog.models.activity_logging.activity_log import Change, model_description
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
        try:
            insight_id = request.data.get("insight_id")
            dashboard_id = request.data.get("dashboard_id")

            if isinstance(dashboard_id, str) or isinstance(dashboard_id, int):
                dashboard: Dashboard = Dashboard.objects.exclude(deleted=True).get(id=dashboard_id, team=self.team)
            else:
                raise Dashboard.DoesNotExist()

            if isinstance(insight_id, str) or isinstance(insight_id, int):
                insight: Insight = Insight.objects.exclude(deleted=True).get(id=insight_id, team=self.team)
            else:
                raise Insight.DoesNotExist()

        except (Dashboard.DoesNotExist, Insight.DoesNotExist):
            raise ValidationError(detail="That dashboard cannot be added to this insight.")

        if dashboard.get_effective_privilege_level(self.request.user.id) <= Dashboard.PrivilegeLevel.CAN_VIEW:
            raise PermissionDenied(f"You don't have permission to add insights to dashboard: {dashboard.name}")

        tiles_before_change = [
            model_description(tile)
            for tile in insight.dashboard_tiles.exclude(deleted=True).exclude(dashboard__deleted=True).all()
        ]

        tile: DashboardTile
        tile, created = DashboardTile.objects.get_or_create(insight=insight, dashboard=dashboard)

        if request.data.get("deleted", None) is not None:
            tile.deleted = request.data.get("deleted", None)
            tile.save()
        else:
            if tile.deleted:  # then we must be undeleting
                tile.deleted = False
                tile.save()

        serializer = BasicDashboardTileSerializer(tile, context={"request": request})

        # with transaction.atomic():
        insight.refresh_from_db()
        log_insight_activity(
            "updated",
            tile.insight,
            int(tile.insight_id),
            str(tile.insight.short_id),
            UUIDT(uuid_str=self.organization_id),
            self.team_id,
            cast(User, self.request.user),
            [
                Change(
                    type="Insight",
                    action="changed",
                    field="dashboards",  # TODO UI is expecting dashboards but should expect dashboard_tiles
                    before=tiles_before_change,
                    after=[
                        model_description(tile)
                        for tile in insight.dashboard_tiles.exclude(deleted=True).exclude(dashboard__deleted=True).all()
                    ],
                )
            ],
        )

        return Response(data=serializer.data, status=status.HTTP_200_OK)
