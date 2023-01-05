import json
from typing import Any, Dict, List, Optional, cast

import structlog
from django.db.models import Prefetch, QuerySet
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.serializer_helpers import ReturnDict

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.insight import InsightSerializer, InsightViewSet
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.constants import INSIGHT_TRENDS, AvailableFeature
from posthog.event_usage import report_user_action
from posthog.helpers import create_dashboard_from_template
from posthog.models import Dashboard, DashboardTile, Insight, Team, Text
from posthog.models.team.team import get_available_features_for_team
from posthog.models.user import User
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.utils import should_ignore_dashboard_items_field

logger = structlog.get_logger(__name__)


class CanEditDashboard(BasePermission):
    message = "You don't have edit permissions for this dashboard."

    def has_object_permission(self, request: Request, view, dashboard) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return view.user_permissions.dashboard(dashboard).can_edit


class TextSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Text
        fields = "__all__"
        read_only_fields = ["id", "created_by", "last_modified_by", "last_modified_at"]


class DashboardTileSerializer(serializers.ModelSerializer):
    id: serializers.IntegerField = serializers.IntegerField(required=False)
    insight = InsightSerializer()
    text = TextSerializer()

    class Meta:
        model = DashboardTile
        exclude = ["dashboard", "deleted", "filters_hash", "last_refresh", "refreshing", "refresh_attempt"]
        read_only_fields = ["id", "insight"]
        depth = 1

    def to_representation(self, instance: Insight):
        representation = super().to_representation(instance)

        insight_representation = representation["insight"] or {}  # May be missing for text tiles

        representation["last_refresh"] = insight_representation.get("last_refresh", None)
        representation["is_cached"] = insight_representation.get("is_cached", False)

        return representation


class DashboardSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    tiles = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)
    use_template = serializers.CharField(write_only=True, allow_blank=True, required=False)
    use_dashboard = serializers.IntegerField(write_only=True, allow_null=True, required=False)
    delete_insights = serializers.BooleanField(write_only=True, required=False, default=False)
    effective_privilege_level = serializers.SerializerMethodField()
    effective_restriction_level = serializers.SerializerMethodField()
    is_shared = serializers.BooleanField(source="is_sharing_enabled", read_only=True, required=False)

    class Meta:
        model = Dashboard
        fields = [
            "id",
            "name",
            "description",
            "items",
            "pinned",
            "created_at",
            "created_by",
            "is_shared",
            "deleted",
            "creation_mode",
            "use_template",
            "use_dashboard",
            "delete_insights",
            "filters",
            "tags",
            "tiles",
            "restriction_level",
            "effective_restriction_level",
            "effective_privilege_level",
        ]
        read_only_fields = ["creation_mode", "effective_restriction_level", "is_shared"]

    def validate_description(self, value: str) -> str:
        available_features = get_available_features_for_team(self.context["team_id"])

        if value and AvailableFeature.DASHBOARD_COLLABORATION not in (available_features or []):
            raise PermissionDenied("You must have paid for dashboard collaboration to set the dashboard description")

        return value

    def validate_filters(self, value) -> Dict:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Filters must be a dictionary")

        return value

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Dashboard:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        team = Team.objects.get(id=self.context["team_id"])
        use_template: str = validated_data.pop("use_template", None)
        use_dashboard: int = validated_data.pop("use_dashboard", None)
        validated_data.pop("delete_insights", None)  # not used during creation
        validated_data = self._update_creation_mode(validated_data, use_template, use_dashboard)
        tags = validated_data.pop("tags", None)  # tags are created separately below as global tag relationships
        dashboard = Dashboard.objects.create(team=team, **validated_data)

        if use_template:
            try:
                create_dashboard_from_template(use_template, dashboard)
            except AttributeError as error:
                logger.error(
                    "dashboard_create.create_from_template_failed",
                    team_id=team.id,
                    template=use_template,
                    error=error,
                    exc_info=True,
                )
                raise serializers.ValidationError({"use_template": "Invalid value provided."})

        elif use_dashboard:
            try:
                existing_dashboard = Dashboard.objects.get(id=use_dashboard, team=team)
                existing_tiles = DashboardTile.objects.filter(dashboard=existing_dashboard).select_related("insight")
                for existing_tile in existing_tiles:
                    if self.initial_data.get("duplicate_tiles", False):
                        self._deep_duplicate_tiles(dashboard, existing_tile)
                    else:
                        existing_tile.copy_to_dashboard(dashboard)

            except Dashboard.DoesNotExist:
                raise serializers.ValidationError({"use_dashboard": "Invalid value provided"})

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

    def _deep_duplicate_tiles(self, dashboard: Dashboard, existing_tile: DashboardTile) -> None:
        if existing_tile.insight:
            new_data = {
                **InsightSerializer(existing_tile.insight, context=self.context).data,
                "id": None,  # to create a new Insight
                "last_refresh": now(),
                "name": (existing_tile.insight.name + " (Copy)") if existing_tile.insight.name else None,
            }
            new_data.pop("dashboards", None)
            new_tags = new_data.pop("tags", None)
            insight_serializer = InsightSerializer(data=new_data, context=self.context)
            insight_serializer.is_valid()
            insight_serializer.save()
            insight = cast(Insight, insight_serializer.instance)

            # Create new insight's tags separately. Force create tags on dashboard duplication.
            self._attempt_set_tags(new_tags, insight, force_create=True)

            DashboardTile.objects.create(
                dashboard=dashboard,
                insight=insight,
                layouts=existing_tile.layouts,
                color=existing_tile.color,
            )
        elif existing_tile.text:
            new_data = {
                **TextSerializer(existing_tile.text, context=self.context).data,
                "id": None,  # to create a new Text
            }
            new_data.pop("dashboards", None)
            text_serializer = TextSerializer(data=new_data, context=self.context)
            text_serializer.is_valid()
            text_serializer.save()
            text = cast(Text, text_serializer.instance)
            DashboardTile.objects.create(
                dashboard=dashboard, text=text, layouts=existing_tile.layouts, color=existing_tile.color
            )

    def update(self, instance: Dashboard, validated_data: Dict, *args: Any, **kwargs: Any) -> Dashboard:
        can_user_restrict = self.context["view"].user_permissions.dashboard(instance).can_restrict
        if "restriction_level" in validated_data and not can_user_restrict:
            raise exceptions.PermissionDenied(
                "Only the dashboard owner and project admins have the restriction rights required to change the dashboard's restriction level."
            )

        validated_data.pop("use_template", None)  # Remove attribute if present

        being_undeleted = instance.deleted and "deleted" in validated_data and not validated_data["deleted"]
        if being_undeleted:
            self._undo_delete_related_tiles(instance)

        initial_data = dict(self.initial_data)

        instance = super().update(instance, validated_data)

        if validated_data.get("deleted", False):
            self._delete_related_tiles(instance, self.validated_data.get("delete_insights", False))

        user = cast(User, self.context["request"].user)
        tiles = initial_data.pop("tiles", [])
        for tile_data in tiles:
            self._update_tiles(instance, tile_data, user)

        if "request" in self.context:
            report_user_action(user, "dashboard updated", instance.get_analytics_metadata())

        return instance

    @staticmethod
    def _update_tiles(instance: Dashboard, tile_data: Dict, user: User) -> None:
        tile_data.pop("is_cached", None)  # read only field

        if tile_data.get("text", None):
            text_json: Dict = tile_data.get("text", {})
            created_by_json = text_json.get("created_by", None)
            if created_by_json:
                last_modified_by = user
                created_by = User.objects.get(id=created_by_json.get("id"))
            else:
                created_by = user
                last_modified_by = None
            text, _ = Text.objects.update_or_create(
                id=text_json.get("id", None),
                defaults={
                    **tile_data["text"],
                    "team": instance.team,
                    "created_by": created_by,
                    "last_modified_by": last_modified_by,
                    "last_modified_at": now(),
                },
            )
            DashboardTile.objects.update_or_create(
                id=tile_data.get("id", None), defaults={**tile_data, "text": text, "dashboard": instance}
            )
        elif "deleted" in tile_data or "color" in tile_data or "layouts" in tile_data:
            tile_data.pop("insight", None)  # don't ever update insight tiles here

            DashboardTile.objects.update_or_create(
                id=tile_data.get("id", None), defaults={**tile_data, "dashboard": instance}
            )

    @staticmethod
    def _delete_related_tiles(instance: Dashboard, delete_related_insights: bool) -> None:
        if delete_related_insights:
            insights_to_update = []
            for insight in Insight.objects.filter(dashboard_tiles__dashboard=instance.id):
                if insight.dashboard_tiles.exclude(deleted=True).count() == 1:
                    insight.deleted = True
                    insights_to_update.append(insight)

            Insight.objects.bulk_update(insights_to_update, ["deleted"])
        DashboardTile.objects.filter(dashboard__id=instance.id).update(deleted=True)

    @staticmethod
    def _undo_delete_related_tiles(instance: Dashboard) -> None:
        DashboardTile.objects.filter(dashboard__id=instance.id).update(deleted=False)
        insights_to_undelete = []
        for tile in DashboardTile.objects.filter(dashboard__id=instance.id):
            if tile.insight and tile.insight.deleted:
                tile.insight.deleted = False
                insights_to_undelete.append(tile.insight)
        Insight.objects.bulk_update(insights_to_undelete, ["deleted"])

    def get_tiles(self, dashboard: Dashboard) -> Optional[List[ReturnDict]]:
        if self.context["view"].action == "list":
            return None

        # used by insight serializer to load insight filters in correct context
        self.context.update({"dashboard": dashboard})

        serialized_tiles = []

        for tile in DashboardTile.dashboard_queryset(dashboard.tiles):
            self.context.update({"dashboard_tile": tile})

            if isinstance(tile.layouts, str):
                tile.layouts = json.loads(tile.layouts)
            tile_data = DashboardTileSerializer(tile, many=False, context=self.context).data
            serialized_tiles.append(tile_data)

        return serialized_tiles

    @extend_schema(deprecated=True, description="items is deprecated, use tiles instead")
    def get_items(self, dashboard: Dashboard):
        if self.context["view"].action == "list" or should_ignore_dashboard_items_field(self.context["request"]):
            return None

        # used by insight serializer to load insight filters in correct context
        self.context.update({"dashboard": dashboard})

        insights = []
        for tile in dashboard.tiles.all():
            self.context.update({"dashboard_tile": tile})
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

    def get_effective_restriction_level(self, dashboard: Dashboard) -> Dashboard.RestrictionLevel:
        return self.context["view"].user_permissions.dashboard(dashboard).effective_restriction_level

    def get_effective_privilege_level(self, dashboard: Dashboard) -> Dashboard.PrivilegeLevel:
        return self.context["view"].user_permissions.dashboard(dashboard).effective_privilege_level

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

        queryset = queryset.prefetch_related("sharingconfiguration_set",).select_related(
            "team__organization",
            "created_by",
        )

        if self.action != "list":
            tiles_prefetch_queryset = DashboardTile.dashboard_queryset(
                DashboardTile.objects.prefetch_related(
                    "caching_states",
                    Prefetch(
                        "insight__dashboards",
                        queryset=Dashboard.objects.exclude(deleted=True)
                        .filter(
                            id__in=DashboardTile.objects.exclude(deleted=True).values_list("dashboard_id", flat=True)
                        )
                        .select_related("team__organization"),
                    ),
                )
            )
            try:
                dashboard_id = self.kwargs["pk"]
                tiles_prefetch_queryset = tiles_prefetch_queryset.filter(dashboard_id=dashboard_id)
            except KeyError:
                # in case there are endpoints that hit this branch but don't have a pk
                pass

            queryset = queryset.prefetch_related(
                # prefetching tiles saves 25 queries per tile on the dashboard
                Prefetch(
                    "tiles",
                    queryset=tiles_prefetch_queryset,
                ),
            )

        return queryset

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pk = kwargs["pk"]
        queryset = self.get_queryset()
        dashboard = get_object_or_404(queryset, pk=pk)
        dashboard.last_accessed_at = now()
        dashboard.save(update_fields=["last_accessed_at"])
        serializer = DashboardSerializer(dashboard, context={"view": self, "request": request})
        return Response(serializer.data)

    @action(methods=["PATCH"], detail=True)
    def move_tile(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # TODO could things be rearranged so this is  PATCH call on a resource and not a custom endpoint?
        tile = request.data["tile"]
        from_dashboard = kwargs["pk"]
        to_dashboard = request.data["toDashboard"]

        tile = DashboardTile.objects.get(dashboard_id=from_dashboard, id=tile["id"])
        tile.dashboard_id = to_dashboard
        tile.save(update_fields=["dashboard_id"])

        serializer = DashboardSerializer(
            Dashboard.objects.get(id=from_dashboard), context={"view": self, "request": request}
        )
        return Response(serializer.data)


class LegacyDashboardsViewSet(DashboardsViewSet):
    legacy_team_compatibility = True

    def get_parents_query_dict(self) -> Dict[str, Any]:
        if not self.request.user.is_authenticated or "share_token" in self.request.GET:
            return {}
        return {"team_id": self.team_id}


class LegacyInsightViewSet(InsightViewSet):
    legacy_team_compatibility = True
