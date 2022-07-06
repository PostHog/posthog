import json
from typing import Any, Dict, cast

from django.db.models import Prefetch, QuerySet
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from rest_framework import exceptions, response, serializers, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.insight import InsightSerializer, InsightViewSet
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.constants import INSIGHT_TRENDS
from posthog.event_usage import report_user_action
from posthog.helpers import create_dashboard_from_template
from posthog.models import Dashboard, DashboardTile, Insight, Team
from posthog.models.user import User
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class CanEditDashboard(BasePermission):
    message = "You don't have edit permissions for this dashboard."

    def has_object_permission(self, request: Request, view, dashboard) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return dashboard.can_user_edit(cast(User, request.user).id)


class DashboardSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)
    use_template = serializers.CharField(write_only=True, allow_blank=True, required=False)
    use_dashboard = serializers.IntegerField(write_only=True, allow_null=True, required=False)
    effective_privilege_level = serializers.SerializerMethodField()
    is_shared = serializers.BooleanField(source="is_sharing_enabled", read_only=True, required=False)

    class Meta:
        model = Dashboard
        fields = [
            "id",
            "name",
            "description",
            "pinned",
            "items",
            "created_at",
            "created_by",
            "is_shared",
            "deleted",
            "creation_mode",
            "use_template",
            "use_dashboard",
            "filters",
            "tags",
            "restriction_level",
            "effective_restriction_level",
            "effective_privilege_level",
        ]
        read_only_fields = ["creation_mode", "effective_restriction_level", "is_shared"]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Dashboard:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        team = Team.objects.get(id=self.context["team_id"])
        use_template: str = validated_data.pop("use_template", None)
        use_dashboard: int = validated_data.pop("use_dashboard", None)
        validated_data = self._update_creation_mode(validated_data, use_template, use_dashboard)
        tags = validated_data.pop("tags", None)  # tags are created separately below as global tag relationships
        dashboard = Dashboard.objects.create(team=team, **validated_data)

        if use_template:
            try:
                create_dashboard_from_template(use_template, dashboard)
            except AttributeError:
                raise serializers.ValidationError({"use_template": "Invalid value provided."})

        elif use_dashboard:
            try:
                from posthog.api.insight import InsightSerializer

                existing_dashboard = Dashboard.objects.get(id=use_dashboard, team=team)
                existing_tiles = DashboardTile.objects.filter(dashboard=existing_dashboard).select_related("insight")
                for existing_tile in existing_tiles:
                    new_data = {
                        **InsightSerializer(existing_tile.insight, context=self.context,).data,
                        "id": None,  # to create a new Insight
                        "last_refresh": now(),
                    }
                    new_data.pop("dashboards", None)
                    new_tags = new_data.pop("tags", None)
                    insight_serializer = InsightSerializer(data=new_data, context=self.context,)
                    insight_serializer.is_valid()
                    insight_serializer.save()
                    insight = cast(Insight, insight_serializer.instance)

                    # Create new insight's tags separately. Force create tags on dashboard duplication.
                    self._attempt_set_tags(new_tags, insight, force_create=True)

                    DashboardTile.objects.create(
                        dashboard=dashboard, insight=insight, layouts=existing_tile.layouts, color=existing_tile.color,
                    )

            except Dashboard.DoesNotExist:
                raise serializers.ValidationError({"use_dashboard": "Invalid value provided"})

        elif request.data.get("items"):
            for item in request.data["items"]:
                insight = Insight.objects.create(
                    **{
                        key: value
                        for key, value in item.items()
                        if key not in ("id", "deleted", "dashboard", "team", "layout", "color")
                    },
                    team=team,
                )
                DashboardTile.objects.create(
                    dashboard=dashboard, insight=insight, layouts=item.get("layouts"), color=item.get("color"),
                )

        # Manual tag creation since this create method doesn't call super()
        self._attempt_set_tags(tags, dashboard)

        report_user_action(
            request.user,
            "dashboard created",
            {
                **dashboard.get_analytics_metadata(),
                "from_template": bool(use_template),
                "template_key": use_template,
                "duplicated": bool(use_dashboard),
                "dashboard_id": use_dashboard,
            },
        )

        return dashboard

    def update(self, instance: Dashboard, validated_data: Dict, *args: Any, **kwargs: Any,) -> Dashboard:
        user = cast(User, self.context["request"].user)
        can_user_restrict = instance.can_user_restrict(user.id)
        if "restriction_level" in validated_data and not can_user_restrict:
            raise exceptions.PermissionDenied(
                "Only the dashboard owner and project admins have the restriction rights required to change the dashboard's restriction level."
            )

        validated_data.pop("use_template", None)  # Remove attribute if present
        instance = super().update(instance, validated_data)

        if validated_data.get("deleted", False):
            DashboardTile.objects.filter(dashboard__id=instance.id).delete()

        initial_data = dict(self.initial_data)

        tile_layouts = initial_data.pop("tile_layouts", [])
        for tile_layout in tile_layouts:
            DashboardTile.objects.filter(dashboard__id=instance.id, insight__id=(tile_layout["id"])).update(
                layouts=tile_layout["layouts"]
            )

        colors = initial_data.pop("colors", [])
        for color in colors:
            DashboardTile.objects.filter(dashboard__id=instance.id, insight__id=(color["id"])).update(
                color=color["color"]
            )

        if "request" in self.context:
            report_user_action(user, "dashboard updated", instance.get_analytics_metadata())

        return instance

    def get_items(self, dashboard: Dashboard):
        if self.context["view"].action == "list":
            return None

        # used by insight serializer to load insight filters in correct context
        self.context.update({"dashboard": dashboard})

        tiles = (
            DashboardTile.objects.filter(dashboard=dashboard)
            .select_related("insight__created_by", "insight__last_modified_by", "insight__team__organization")
            .prefetch_related("insight__dashboards__team__organization")
            .order_by("insight__order")
        )

        insights = []
        for tile in tiles:
            if tile.insight:
                insight = tile.insight
                layouts = tile.layouts
                # workaround because DashboardTiles layouts were migrated as stringified JSON :/
                if isinstance(layouts, str):
                    layouts = json.loads(layouts)

                color = tile.color

                # Make sure all items have an insight set
                if not insight.filters.get("insight"):
                    insight.filters["insight"] = INSIGHT_TRENDS
                    insight.save(update_fields=["filters"])

                self.context.update({"filters_hash": tile.filters_hash})
                insight_data = InsightSerializer(insight, many=False, context=self.context).data
                insight_data["layouts"] = layouts
                insight_data["color"] = color
                insights.append(insight_data)

        return insights

    def get_effective_privilege_level(self, dashboard: Dashboard) -> Dashboard.PrivilegeLevel:
        return dashboard.get_effective_privilege_level(self.context["request"].user.id)

    def validate(self, data):
        if data.get("use_dashboard", None) and data.get("use_template", None):
            raise serializers.ValidationError("`use_dashboard` and `use_template` cannot be used together")
        return data

    def _update_creation_mode(self, validated_data, use_template: str, use_dashboard: int):
        if use_template:
            return {**validated_data, "creation_mode": "template"}
        if use_dashboard:
            return {**validated_data, "creation_mode": "duplicate"}

        return {**validated_data, "creation_mode": "default"}


class DashboardsViewSet(TaggedItemViewSetMixin, StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Dashboard.objects.order_by("name")
    serializer_class = DashboardSerializer
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
        CanEditDashboard,
    ]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if not self.action.endswith("update"):
            # Soft-deleted dashboards can be brought back with a PATCH request
            queryset = queryset.filter(deleted=False)

        queryset = (
            queryset.prefetch_related("sharingconfiguration_set")
            .select_related("team__organization", "created_by")
            .prefetch_related(Prefetch("insights", queryset=Insight.objects.filter(deleted=False).order_by("order"),),)
        )
        return queryset

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        pk = kwargs["pk"]
        queryset = self.get_queryset()
        dashboard = get_object_or_404(queryset, pk=pk)
        dashboard.last_accessed_at = now()
        dashboard.save(update_fields=["last_accessed_at"])
        serializer = DashboardSerializer(dashboard, context={"view": self, "request": request})
        return response.Response(serializer.data)


class LegacyDashboardsViewSet(DashboardsViewSet):
    legacy_team_compatibility = True

    def get_parents_query_dict(self) -> Dict[str, Any]:
        if not self.request.user.is_authenticated or "share_token" in self.request.GET:
            return {}
        return {"team_id": self.team_id}


class LegacyInsightViewSet(InsightViewSet):
    legacy_team_compatibility = True
