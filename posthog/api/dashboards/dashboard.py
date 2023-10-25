import json
from typing import Any, Dict, List, Optional, Type, cast
from rest_framework.serializers import BaseSerializer

import structlog
from django.db.models import Prefetch, QuerySet
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.serializer_helpers import ReturnDict

from posthog.api.dashboards.dashboard_template_json_schema_parser import (
    DashboardTemplateCreationJSONSchemaParser,
)
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.insight import InsightSerializer, InsightViewSet
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.constants import AvailableFeature
from posthog.event_usage import report_user_action
from posthog.helpers import create_dashboard_from_template
from posthog.helpers.dashboard_templates import create_from_template
from posthog.models import Dashboard, DashboardTile, Insight, Text
from posthog.models.dashboard_templates import DashboardTemplate
from posthog.models.tagged_item import TaggedItem
from posthog.models.team.team import check_is_feature_available_for_team
from posthog.models.user import User
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    TeamMemberAccessPermission,
)
from posthog.user_permissions import UserPermissionsSerializerMixin

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
        exclude = [
            "dashboard",
            "deleted",
            "filters_hash",
            "last_refresh",
            "refreshing",
            "refresh_attempt",
        ]
        read_only_fields = ["id", "insight"]
        depth = 1

    def to_representation(self, instance: DashboardTile):
        representation = super().to_representation(instance)

        insight_representation = representation["insight"] or {}  # May be missing for text tiles

        representation["last_refresh"] = insight_representation.get("last_refresh", None)
        representation["is_cached"] = insight_representation.get("is_cached", False)

        return representation


class DashboardBasicSerializer(
    TaggedItemSerializerMixin,
    serializers.ModelSerializer,
    UserPermissionsSerializerMixin,
):
    created_by = UserBasicSerializer(read_only=True)
    effective_privilege_level = serializers.SerializerMethodField()
    effective_restriction_level = serializers.SerializerMethodField()
    is_shared = serializers.BooleanField(source="is_sharing_enabled", read_only=True, required=False)

    class Meta:
        model = Dashboard
        fields = [
            "id",
            "name",
            "description",
            "pinned",
            "created_at",
            "created_by",
            "is_shared",
            "deleted",
            "creation_mode",
            "tags",
            "restriction_level",
            "effective_restriction_level",
            "effective_privilege_level",
        ]
        read_only_fields = fields

    def get_effective_restriction_level(self, dashboard: Dashboard) -> Dashboard.RestrictionLevel:
        if self.context.get("is_shared"):
            return Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        return self.user_permissions.dashboard(dashboard).effective_restriction_level

    def get_effective_privilege_level(self, dashboard: Dashboard) -> Dashboard.PrivilegeLevel:
        if self.context.get("is_shared"):
            return Dashboard.PrivilegeLevel.CAN_VIEW
        return self.user_permissions.dashboard(dashboard).effective_privilege_level


class DashboardSerializer(DashboardBasicSerializer):
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
        if value and not check_is_feature_available_for_team(
            self.context["team_id"], AvailableFeature.DASHBOARD_COLLABORATION
        ):
            raise PermissionDenied("You must have paid for dashboard collaboration to set the dashboard description")
        return value

    def validate_filters(self, value) -> Dict:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Filters must be a dictionary")

        return value

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Dashboard:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        team_id = self.context["team_id"]
        use_template: str = validated_data.pop("use_template", None)
        use_dashboard: int = validated_data.pop("use_dashboard", None)
        validated_data.pop("delete_insights", None)  # not used during creation
        validated_data = self._update_creation_mode(validated_data, use_template, use_dashboard)
        tags = validated_data.pop("tags", None)  # tags are created separately below as global tag relationships
        dashboard = Dashboard.objects.create(team_id=team_id, **validated_data)

        if use_template:
            try:
                create_dashboard_from_template(use_template, dashboard)
            except AttributeError as error:
                logger.error(
                    "dashboard_create.create_from_template_failed",
                    team_id=team_id,
                    template=use_template,
                    error=error,
                    exc_info=True,
                )
                raise serializers.ValidationError({"use_template": f"Invalid template provided: {use_template}"})

        elif use_dashboard:
            try:
                existing_dashboard = Dashboard.objects.get(id=use_dashboard, team_id=team_id)
                existing_tiles = (
                    DashboardTile.objects.filter(dashboard=existing_dashboard)
                    .exclude(deleted=True)
                    .select_related("insight")
                )
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
                dashboard=dashboard,
                text=text,
                layouts=existing_tile.layouts,
                color=existing_tile.color,
            )

    def update(self, instance: Dashboard, validated_data: Dict, *args: Any, **kwargs: Any) -> Dashboard:
        can_user_restrict = self.user_permissions.dashboard(instance).can_restrict
        if "restriction_level" in validated_data and not can_user_restrict:
            raise exceptions.PermissionDenied(
                "Only the dashboard owner and project admins have the restriction rights required to change the dashboard's restriction level."
            )

        validated_data.pop("use_template", None)  # Remove attribute if present

        being_undeleted = instance.deleted and "deleted" in validated_data and not validated_data["deleted"]
        if being_undeleted:
            self._undo_delete_related_tiles(instance)

        initial_data = dict(self.initial_data)

        if validated_data.get("deleted", False):
            self._delete_related_tiles(instance, self.validated_data.get("delete_insights", False))

        instance = super().update(instance, validated_data)

        user = cast(User, self.context["request"].user)
        tiles = initial_data.pop("tiles", [])
        for tile_data in tiles:
            self._update_tiles(instance, tile_data, user)

        if "request" in self.context:
            report_user_action(user, "dashboard updated", instance.get_analytics_metadata())

        self.user_permissions.reset_insights_dashboard_cached_results()
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
                id=tile_data.get("id", None),
                defaults={**tile_data, "text": text, "dashboard": instance},
            )
        elif "deleted" in tile_data or "color" in tile_data or "layouts" in tile_data:
            tile_data.pop("insight", None)  # don't ever update insight tiles here

            DashboardTile.objects.update_or_create(
                id=tile_data.get("id", None),
                defaults={**tile_data, "dashboard": instance},
            )

    @staticmethod
    def _delete_related_tiles(instance: Dashboard, delete_related_insights: bool) -> None:
        if delete_related_insights:
            insights_to_update = []
            for insight in Insight.objects.filter(dashboard_tiles__dashboard=instance.id):
                if insight.dashboard_tiles.count() == 1:
                    insight.deleted = True
                    insights_to_update.append(insight)

            Insight.objects.bulk_update(insights_to_update, ["deleted"])
        DashboardTile.objects_including_soft_deleted.filter(dashboard__id=instance.id).update(deleted=True)

    @staticmethod
    def _undo_delete_related_tiles(instance: Dashboard) -> None:
        DashboardTile.objects_including_soft_deleted.filter(dashboard__id=instance.id).update(deleted=False)
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

        tiles = DashboardTile.dashboard_queryset(dashboard.tiles).prefetch_related(
            Prefetch(
                "insight__tagged_items",
                queryset=TaggedItem.objects.select_related("tag"),
                to_attr="prefetched_tags",
            )
        )
        self.user_permissions.set_preloaded_dashboard_tiles(list(tiles))

        for tile in tiles:
            self.context.update({"dashboard_tile": tile})

            if isinstance(tile.layouts, str):
                tile.layouts = json.loads(tile.layouts)

            tile_data = DashboardTileSerializer(tile, many=False, context=self.context).data
            serialized_tiles.append(tile_data)

        return serialized_tiles

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


class DashboardsViewSet(
    TaggedItemViewSetMixin,
    StructuredViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    queryset = Dashboard.objects.order_by("name")
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
        CanEditDashboard,
    ]

    def get_serializer_class(self) -> Type[BaseSerializer]:
        return DashboardBasicSerializer if self.action == "list" else DashboardSerializer

    def get_queryset(self) -> QuerySet:
        if (
            self.action == "partial_update"
            and "deleted" in self.request.data
            and not self.request.data.get("deleted")
            and len(self.request.data) == 1
        ):
            # a dashboard can be un-deleted by patching {"deleted": False}
            queryset = Dashboard.objects_including_soft_deleted
        else:
            queryset = super().get_queryset()

        queryset = queryset.prefetch_related("sharingconfiguration_set").select_related(
            "team__organization",
            "created_by",
        )

        if self.action != "list":
            tiles_prefetch_queryset = DashboardTile.dashboard_queryset(
                DashboardTile.objects.prefetch_related(
                    "caching_states",
                    Prefetch(
                        "insight__dashboards",
                        queryset=Dashboard.objects.filter(
                            id__in=DashboardTile.objects.values_list("dashboard_id", flat=True)
                        ).select_related("team__organization"),
                    ),
                    "insight__dashboard_tiles__dashboard",
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
            Dashboard.objects.get(id=from_dashboard),
            context={"view": self, "request": request},
        )
        return Response(serializer.data)

    @action(
        methods=["POST"],
        detail=False,
        parser_classes=[DashboardTemplateCreationJSONSchemaParser],
    )
    def create_from_template_json(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        dashboard = Dashboard.objects.create(team_id=self.team_id)

        try:
            dashboard_template = DashboardTemplate(**request.data["template"])
            create_from_template(dashboard, dashboard_template)

            report_user_action(
                cast(User, request.user),
                "dashboard created",
                {
                    **dashboard.get_analytics_metadata(),
                    "from_template": True,
                    "template_key": dashboard_template.template_name,
                    "duplicated": False,
                    "dashboard_id": dashboard.pk,
                },
            )
        except Exception as e:
            dashboard.delete()
            raise e

        return Response(DashboardSerializer(dashboard, context={"view": self, "request": request}).data)


class LegacyDashboardsViewSet(DashboardsViewSet):
    legacy_team_compatibility = True

    def get_parents_query_dict(self) -> Dict[str, Any]:
        if not self.request.user.is_authenticated or "share_token" in self.request.GET:
            return {}
        return {"team_id": self.team_id}


class LegacyInsightViewSet(InsightViewSet):
    legacy_team_compatibility = True
