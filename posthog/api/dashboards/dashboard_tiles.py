from typing import Any, Callable, Dict, List, Optional, cast

import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import Dashboard, DashboardTile, Insight, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.utils import UUIDT
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission

logger = structlog.get_logger(__name__)


class BasicDashboardTileSerializer(serializers.Serializer):
    """
    Serializes a tile to only the insight and dashboard ids that it links to
    TODO: so wait, what about text tiles?
    """

    insight_id: serializers.IntegerField = serializers.IntegerField(required=True)
    dashboard_id: serializers.IntegerField = serializers.IntegerField(required=True)

    def validate_insight_id(self, value: int) -> int:
        team_id = self.context["team_id"]
        insight = Insight.objects.get(id=value)

        if insight.team_id != team_id:
            raise PermissionDenied("You cannot access this insight")

        if insight.deleted:
            raise ValidationError("You cannot use deleted insights in a dashboard tile")

        return value

    def validate_dashboard_id(self, value: int) -> int:
        team_id = self.context["team_id"]
        dashboard = Dashboard.objects.get(id=value)

        if dashboard.team_id != team_id:
            raise PermissionDenied("You cannot access this dashboard")

        if dashboard.deleted:
            raise ValidationError("You add tiles to deleted dashboards")

        if (
            dashboard.get_effective_privilege_level(self.context["request"].user.id)
            == Dashboard.PrivilegeLevel.CAN_VIEW
        ):
            raise PermissionDenied(f"You don't have permission to add insights to dashboard: {dashboard.id}")

        return value

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> DashboardTile:
        insight = Insight.objects.get(id=validated_data["insight_id"])
        dashboard = Dashboard.objects.get(id=validated_data["dashboard_id"])

        tile, created = DashboardTile.objects.get_or_create(dashboard=dashboard, insight=insight)
        if not created and tile.deleted:
            tile.deleted = False
            tile.save()

        return tile


class DashboardTileViewSet(
    StructuredViewSetMixin,
    ForbidDestroyModel,
    viewsets.GenericViewSet,
):
    queryset = DashboardTile.objects.all()
    serializer_class = BasicDashboardTileSerializer
    filter_rewrite_rules = {"team_id": "dashboard__team_id"}
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        self._write_to_activity_log(
            insight_id=serializer.validated_data["insight_id"],
            dashboard_id=serializer.validated_data["dashboard_id"],
            user=cast(User, request.user),
            # only need to flag that a dashboard was added
            before=lambda x: [],
            after=lambda tile: [{"dashboard": {"id": tile.dashboard.id, "name": tile.dashboard.name}}],
        )

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=False)
    def remove(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        self.get_queryset().filter(**serializer.validated_data).update(deleted=True)

        self._write_to_activity_log(
            insight_id=serializer.validated_data["insight_id"],
            dashboard_id=serializer.validated_data["dashboard_id"],
            user=request.user,  # type: ignore
            # only need to flag the removed dashboard to the log
            after=lambda x: [],
            before=lambda tile: [{"dashboard": {"id": tile.dashboard.id, "name": tile.dashboard.name}}],
        )

        return Response(status=status.HTTP_200_OK)

    def _write_to_activity_log(
        self,
        insight_id: int,
        dashboard_id: int,
        user: User,
        before: Optional[Callable[[DashboardTile], Optional[Any]]] = None,
        after: Optional[Callable[[DashboardTile], Optional[Any]]] = None,
    ) -> None:
        try:
            dashboard_tile = (
                DashboardTile.objects.filter(
                    insight_id=insight_id,
                    dashboard_id=dashboard_id,
                )
                .select_related("dashboard", "insight")
                .first()
            )
            if not dashboard_tile or not dashboard_tile.insight:
                raise DashboardTile.DoesNotExist("the requested tile doesn't exist")
            changes: List[Change] = [
                Change(
                    type="Insight",
                    action="changed",
                    field="dashboards",
                    before=before(dashboard_tile) if before else None,
                    after=after(dashboard_tile) if after else None,
                )
            ]
            log_activity(
                organization_id=UUIDT(uuid_str=self.organization_id),
                team_id=self.team_id,
                user=user,
                item_id=insight_id,
                scope="Insight",
                activity="updated",
                detail=Detail(
                    name=dashboard_tile.insight.name
                    if dashboard_tile.insight.name
                    else dashboard_tile.insight.derived_name,
                    changes=changes,
                    short_id=dashboard_tile.insight.short_id,
                ),
            )
        except Exception as e:
            logger.error(
                "dashboard_tiles.failed_while_adding_to_activity_log",
                exc_info=True,
                exc=e,
                team_id=self.team_id,
                insight_id=insight_id,
                dashboard_id=dashboard_id,
            )
