import json
from collections.abc import AsyncGenerator
from contextlib import nullcontext
from typing import Any, Optional, cast

from django.conf import settings
from django.db.models import Prefetch, QuerySet
from django.dispatch import receiver
from django.http import StreamingHttpResponse
from django.utils.timezone import now

import structlog
import pydantic_core
import posthoganalytics
from asgiref.sync import sync_to_async
from opentelemetry import trace
from rest_framework import exceptions, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.utils.serializer_helpers import ReturnDict

from posthog.api.dashboards.dashboard_template_json_schema_parser import DashboardTemplateCreationJSONSchemaParser
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.insight import InsightSerializer, InsightViewSet
from posthog.api.monitoring import Feature, monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import action
from posthog.clickhouse.client.async_task_chain import task_chain_context
from posthog.constants import GENERATED_DASHBOARD_PREFIX
from posthog.event_usage import report_user_action
from posthog.helpers import create_dashboard_from_template
from posthog.helpers.dashboard_templates import create_from_template
from posthog.models import Dashboard, DashboardTile, Insight, Text
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.alert import AlertConfiguration
from posthog.models.dashboard_templates import DashboardTemplate
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.insight_variable import InsightVariable
from posthog.models.signals import model_activity_signal
from posthog.models.tagged_item import TaggedItem
from posthog.models.user import User
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer
from posthog.user_permissions import UserPermissionsSerializerMixin
from posthog.utils import filters_override_requested_by_client, variables_override_requested_by_client

from ee.hogai.utils.aio import async_to_sync

logger = structlog.get_logger(__name__)

DASHBOARD_SHARED_FIELDS = [
    "id",
    "name",
    "description",
    "pinned",
    "created_at",
    "created_by",
    "last_accessed_at",
    "is_shared",
    "deleted",
    "creation_mode",
    "filters",
    "variables",
    "breakdown_colors",
    "data_color_theme_id",
    "tags",
    "restriction_level",
    "effective_restriction_level",
    "effective_privilege_level",
    "user_access_level",
    "access_control_version",
    "last_refresh",
    "persisted_filters",
    "persisted_variables",
    "team_id",
]


tracer = trace.get_tracer(__name__)


def serialize_tile_with_context(tile, order: int, context: dict) -> tuple[int, dict]:
    """
    Serialize a single tile with error handling. Returns (order, tile_data) tuple.
    This function is designed to be thread-safe and used with ThreadPoolExecutor.
    """
    # Create a copy of context to avoid thread conflicts
    tile_context = context.copy()
    tile_context.update(
        {
            "dashboard_tile": tile,
            "order": order,
        }
    )

    if isinstance(tile.layouts, str):
        tile.layouts = json.loads(tile.layouts)

    try:
        tile_data = DashboardTileSerializer(tile, many=False, context=tile_context).data
        return order, tile_data
    except pydantic_core.ValidationError as e:
        if not tile.insight:
            raise
        query = tile.insight.query
        tile.insight.query = None
        tile_data = DashboardTileSerializer(tile, context=tile_context).data
        tile_data["insight"]["query"] = query
        tile_data["error"] = {"type": type(e).__name__, "message": str(e)}
        return order, tile_data


class CanEditDashboard(BasePermission):
    message = "You don't have edit permissions for this dashboard."

    def has_object_permission(self, request: Request, view, dashboard) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return view.user_permissions.dashboard(dashboard).can_edit


class TextSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)
    body = serializers.CharField(
        max_length=4000,
        required=False,
        allow_blank=True,
        allow_null=True,
        error_messages={"max_length": "Text body cannot exceed 4000 characters"},
    )

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

    @tracer.start_as_current_span("DashboardTileSerializer.to_representation")
    def to_representation(self, instance: DashboardTile):
        representation = super().to_representation(instance)

        representation["order"] = self.context.get("order", None)

        insight_representation = representation["insight"] or {}  # May be missing for text tiles
        representation["last_refresh"] = insight_representation.get("last_refresh", None)
        representation["is_cached"] = insight_representation.get("is_cached", False)

        return representation


class DashboardBasicSerializer(
    TaggedItemSerializerMixin,
    serializers.ModelSerializer,
    UserPermissionsSerializerMixin,
    UserAccessControlSerializerMixin,
):
    created_by = UserBasicSerializer(read_only=True)
    effective_privilege_level = serializers.SerializerMethodField()
    effective_restriction_level = serializers.SerializerMethodField()
    access_control_version = serializers.SerializerMethodField()
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
            "last_accessed_at",
            "is_shared",
            "deleted",
            "creation_mode",
            "tags",
            "restriction_level",
            "effective_restriction_level",
            "effective_privilege_level",
            "user_access_level",
            "access_control_version",
            "last_refresh",
            "team_id",
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

    def get_access_control_version(self, dashboard: Dashboard) -> str:
        # This effectively means that the dashboard they are using the old dashboard permissions
        if dashboard.restriction_level > Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT:
            return "v1"
        return "v2"


class DashboardMetadataSerializer(DashboardBasicSerializer):
    filters = serializers.SerializerMethodField()
    variables = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)
    effective_privilege_level = serializers.SerializerMethodField()
    effective_restriction_level = serializers.SerializerMethodField()
    access_control_version = serializers.SerializerMethodField()
    is_shared = serializers.BooleanField(source="is_sharing_enabled", read_only=True, required=False)
    breakdown_colors = serializers.JSONField(required=False)
    data_color_theme_id = serializers.IntegerField(required=False, allow_null=True)
    persisted_filters = serializers.SerializerMethodField()
    persisted_variables = serializers.SerializerMethodField()

    class Meta:
        model = Dashboard
        fields = DASHBOARD_SHARED_FIELDS
        read_only_fields = ["creation_mode", "effective_restriction_level", "is_shared", "user_access_level"]

    def get_filters(self, dashboard: Dashboard) -> dict:
        request = self.context.get("request")
        return filters_override_requested_by_client(request, dashboard)

    def get_variables(self, dashboard: Dashboard) -> dict | None:
        request = self.context.get("request")
        return variables_override_requested_by_client(request, dashboard, list(self.context["insight_variables"]))

    def get_persisted_filters(self, dashboard: Dashboard) -> dict | None:
        return dashboard.filters if dashboard.filters else None

    def get_persisted_variables(self, dashboard: Dashboard) -> dict | None:
        return dashboard.variables if dashboard.variables else None


class DashboardSerializer(DashboardMetadataSerializer):
    tiles = serializers.SerializerMethodField()
    use_template = serializers.CharField(write_only=True, allow_blank=True, required=False)
    use_dashboard = serializers.IntegerField(write_only=True, allow_null=True, required=False)
    delete_insights = serializers.BooleanField(write_only=True, required=False, default=False)
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Dashboard
        fields = [
            *DASHBOARD_SHARED_FIELDS,
            "tiles",
            "use_template",
            "use_dashboard",
            "delete_insights",
            "_create_in_folder",
        ]
        read_only_fields = ["creation_mode", "effective_restriction_level", "is_shared", "user_access_level"]

    def validate_filters(self, value) -> dict:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Filters must be a dictionary")

        return value

    def validate_variables(self, value) -> dict:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Variables must be a dictionary")

        return value

    @monitor(feature=Feature.DASHBOARD, endpoint="dashboard", method="POST")
    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Dashboard:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        team_id = self.context["team_id"]
        use_template: str = validated_data.pop("use_template", None)
        use_dashboard: int = validated_data.pop("use_dashboard", None)
        validated_data.pop("delete_insights", None)  # not used during creation
        validated_data = self._update_creation_mode(validated_data, use_template, use_dashboard)
        tags = validated_data.pop("tags", None)  # tags are created separately below as global tag relationships
        current_url = request.headers.get("Referer")
        session_id = request.headers.get("X-Posthog-Session-Id")

        request_filters = request.data.get("filters")
        if request_filters:
            if not isinstance(request_filters, dict):
                raise serializers.ValidationError("Filters must be a dictionary")
            filters = request_filters
        else:
            filters = {}
        dashboard = Dashboard.objects.create(team_id=team_id, filters=filters, **validated_data)

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
                existing_dashboard = Dashboard.objects.get(
                    id=use_dashboard, team__project_id=self.context["get_team"]().project_id
                )
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
                "$current_url": current_url,
                "$session_id": session_id,
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
                filters_overrides=existing_tile.filters_overrides,
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
                filters_overrides=existing_tile.filters_overrides,
            )

    @monitor(feature=Feature.DASHBOARD, endpoint="dashboard", method="PATCH")
    def update(self, instance: Dashboard, validated_data: dict, *args: Any, **kwargs: Any) -> Dashboard:
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
            group_type_mapping = GroupTypeMapping.objects.filter(
                team=instance.team, project_id=instance.team.project_id, detail_dashboard=instance
            ).first()
            if group_type_mapping:
                group_type_mapping.detail_dashboard = None
                group_type_mapping.save()

        request_filters = initial_data.get("filters")
        if request_filters:
            if not isinstance(request_filters, dict):
                raise serializers.ValidationError("Filters must be a dictionary")
            instance.filters = request_filters

        request_variables = initial_data.get("variables")
        if request_variables:
            if not isinstance(request_variables, dict):
                raise serializers.ValidationError("Filters must be a dictionary")
            instance.variables = request_variables

        instance = super().update(instance, validated_data)

        user = cast(User, self.context["request"].user)
        tiles = initial_data.pop("tiles", [])
        for tile_data in tiles:
            self._update_tiles(instance, tile_data, user)

        duplicate_tiles = initial_data.pop("duplicate_tiles", [])
        for tile_data in duplicate_tiles:
            existing_tile = DashboardTile.objects.get(dashboard=instance, id=tile_data["id"])
            existing_tile.layouts = {}
            self._deep_duplicate_tiles(instance, existing_tile)

        if "request" in self.context:
            report_user_action(user, "dashboard updated", instance.get_analytics_metadata())

        self.user_permissions.reset_insights_dashboard_cached_results()
        return instance

    @staticmethod
    def _update_tiles(instance: Dashboard, tile_data: dict, user: User) -> None:
        tile_data.pop("is_cached", None)  # read only field
        tile_data.pop("order", None)  # read only field

        if tile_data.get("text", None):
            text_json: dict = tile_data.get("text", {})
            created_by_json = text_json.get("created_by", None)
            if created_by_json:
                last_modified_by = user
                created_by = User.objects.get(id=created_by_json.get("id"))
            else:
                created_by = user
                last_modified_by = None

            text_data = {**tile_data["text"], "team": instance.team_id}
            text_serializer = TextSerializer(data=text_data)
            if not text_serializer.is_valid():
                raise serializers.ValidationError({"text": text_serializer.errors})

            validated_data = text_serializer.validated_data
            validated_data["created_by"] = created_by
            validated_data["last_modified_by"] = last_modified_by
            validated_data["last_modified_at"] = now()

            text, _ = Text.objects.update_or_create(id=text_json.get("id", None), defaults=validated_data)
            DashboardTile.objects.update_or_create(
                id=tile_data.get("id", None),
                defaults={**tile_data, "text": text, "dashboard": instance},
            )
        elif (
            "deleted" in tile_data or "color" in tile_data or "layouts" in tile_data or "filters_overrides" in tile_data
        ):
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

    @tracer.start_as_current_span("DashboardSerializer.get_tiles")
    def get_tiles(self, dashboard: Dashboard) -> Optional[list[ReturnDict]]:
        if self.context["view"].action == "list":
            return None

        # used by insight serializer to load insight filters in correct context
        self.context.update({"dashboard": dashboard})

        serialized_tiles: list[ReturnDict] = []

        tiles = DashboardTile.dashboard_queryset(dashboard.tiles.all()).prefetch_related(
            Prefetch(
                "insight__tagged_items",
                queryset=TaggedItem.objects.select_related("tag"),
                to_attr="prefetched_tags",
            ),
            Prefetch(
                "insight__alertconfiguration_set",
                queryset=AlertConfiguration.objects.select_related("created_by"),
                to_attr="_prefetched_alerts",
            ),
        )
        self.user_permissions.set_preloaded_dashboard_tiles(list(tiles))

        team = self.context["get_team"]()
        chained_tile_refresh_enabled = posthoganalytics.feature_enabled(
            "chained_dashboard_tile_refresh",
            str(team.organization_id),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
        )

        layout_size = "sm"  # default layout size

        # Sort tiles by layout to ensure insights are computed in order of appearance on dashboard
        # Use the specified layout size to get the correct order for the current viewport
        sorted_tiles = sorted(
            tiles,
            key=lambda tile: (
                tile.layouts.get(layout_size, {}).get("y", 100),
                tile.layouts.get(layout_size, {}).get("x", 100),
            ),
        )

        with task_chain_context() if chained_tile_refresh_enabled else nullcontext():
            # Handle case where there are no tiles
            if not sorted_tiles:
                return []

            for order, tile in enumerate(sorted_tiles):
                order, tile_data = serialize_tile_with_context(tile, order, self.context)
                serialized_tiles.append(cast(ReturnDict, tile_data))

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
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    TaggedItemViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "dashboard"
    queryset = Dashboard.objects_including_soft_deleted.order_by("-pinned", "name")
    permission_classes = [CanEditDashboard]
    renderer_classes = [SafeJSONRenderer, ServerSentEventRenderer]

    @tracer.start_as_current_span("DashboardViewSet.get_serializer_context")
    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["insight_variables"] = InsightVariable.objects.filter(team=self.team).all()

        return context

    def get_serializer_class(self) -> type[BaseSerializer]:
        return DashboardBasicSerializer if self.action == "list" else DashboardSerializer

    def filter_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = super().filter_queryset(queryset)
        tags = self.request.query_params.getlist("tags")
        if not tags:
            return queryset

        return queryset.filter(tagged_items__tag__name__in=tags).distinct()

    @tracer.start_as_current_span("DashboardViewSet.dangerously_get_queryset")
    def dangerously_get_queryset(self):
        # Dashboards are retrieved under /environments/ because they include team-specific query results,
        # but they are in fact project-level, rather than environment-level
        assert self.team.project_id is not None
        queryset = self.queryset.filter(team__project_id=self.team.project_id)

        include_deleted = (
            self.action == "partial_update"
            and "deleted" in self.request.data
            and not self.request.data.get("deleted")
            and len(self.request.data) == 1
        )

        if not include_deleted:
            # a dashboard can be un-deleted by patching {"deleted": False}
            queryset = queryset.exclude(deleted=True)

        queryset = queryset.prefetch_related("sharingconfiguration_set").select_related("created_by")

        if self.action != "list":
            tiles_prefetch_queryset = DashboardTile.dashboard_queryset(
                DashboardTile.objects.prefetch_related(
                    "caching_states",
                    Prefetch(
                        "insight__dashboards",
                        queryset=Dashboard.objects.filter(
                            id__in=DashboardTile.objects.values_list("dashboard_id", flat=True)
                        ),
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

        # Add access level filtering for list actions
        queryset = self._filter_queryset_by_access_level(queryset)

        # Filter out generated dashboards if requested (for list action only)
        if self.action == "list" and self.request.query_params.get("exclude_generated") == "true":
            queryset = queryset.exclude(name__startswith=GENERATED_DASHBOARD_PREFIX)

        return queryset

    @monitor(feature=Feature.DASHBOARD, endpoint="dashboard", method="GET")
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        dashboard = self.get_object()
        dashboard.last_accessed_at = now()
        dashboard.save(update_fields=["last_accessed_at"])
        serializer = DashboardSerializer(dashboard, context=self.get_serializer_context())
        return Response(serializer.data)

    # ******************************************
    # /projects/:id/dashboard/:id/stream_tiles
    # ******************************************
    @action(methods=["GET"], detail=True, url_path="stream_tiles")
    def stream_tiles(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse:
        """Stream dashboard metadata and tiles via Server-Sent Events. Sends metadata first, then tiles as they are rendered."""
        dashboard = self.get_object()  # This will raise 404 if not found - let it bubble up normally

        # Do all database operations and data loading synchronously first
        dashboard.last_accessed_at = now()
        dashboard.save(update_fields=["last_accessed_at"])

        # Prepare metadata with initial tiles
        metadata_serializer = DashboardMetadataSerializer(dashboard, context=self.get_serializer_context())
        metadata_data = metadata_serializer.data

        # Create serializer context for tiles
        context = self.get_serializer_context()
        context.update({"dashboard": dashboard})

        # Get tiles with proper prefetch
        tiles = DashboardTile.dashboard_queryset(dashboard.tiles.all()).prefetch_related(
            Prefetch(
                "insight__tagged_items",
                queryset=TaggedItem.objects.select_related("tag"),
                to_attr="prefetched_tags",
            )
        )

        layout_size = self._get_layout_size_from_request(request)

        sorted_tiles = sorted(
            tiles,
            key=lambda tile: (
                tile.layouts.get(layout_size, {}).get("y", 100),
                tile.layouts.get(layout_size, {}).get("x", 100),
            ),
        )

        # Async generator that handles progressive tile serialization and streaming
        async def async_tile_stream_generator() -> AsyncGenerator[bytes, None]:
            renderer = SafeJSONRenderer()

            try:
                # Serialize the first 2 tiles (or fewer if dashboard has less) for inclusion in metadata
                initial_tiles = []
                initial_tile_count = min(2, len(sorted_tiles))

                for order in range(initial_tile_count):
                    tile = sorted_tiles[order]
                    try:
                        order_result, tile_data = await sync_to_async(
                            serialize_tile_with_context, thread_sensitive=True
                        )(tile, order, context)
                        initial_tiles.append(tile_data)
                    except Exception as e:
                        logger.exception(f"Error serializing initial tile {tile.id}: {e}")
                        # Add error tile to initial tiles
                        initial_tiles.append(
                            {
                                "id": tile.id,
                                "error": {"type": type(e).__name__, "message": str(e)},
                            }
                        )

                metadata_data["tiles"] = initial_tiles

                metadata_json = renderer.render({"type": "metadata", "dashboard": metadata_data}).decode()
                yield f"data: {metadata_json}\n\n".encode()

                # Stream remaining tiles (starting from tile 2 if we have more than 2 tiles)
                for order in range(initial_tile_count, len(sorted_tiles)):
                    tile = sorted_tiles[order]
                    try:
                        order_result, tile_data = await sync_to_async(
                            serialize_tile_with_context, thread_sensitive=True
                        )(tile, order, context)
                        tile_json = renderer.render({"type": "tile", "order": order, "tile": tile_data}).decode()
                        yield f"data: {tile_json}\n\n".encode()
                    except Exception as e:
                        logger.exception(f"Error serializing tile {tile.id}: {e}")
                        error_json = renderer.render({"type": "error", "tile_id": tile.id, "error": str(e)}).decode()
                        yield f"data: {error_json}\n\n".encode()

                # Send completion signal
                complete_json = renderer.render({"type": "complete"}).decode()
                yield f"data: {complete_json}\n\n".encode()

            except Exception as e:
                logger.exception(f"Error in tile streaming: {e}")
                error_json = renderer.render({"type": "error", "error": str(e)}).decode()
                yield f"data: {error_json}\n\n".encode()

        response = StreamingHttpResponse(
            streaming_content=(
                async_tile_stream_generator()
                if settings.SERVER_GATEWAY_INTERFACE == "ASGI"
                else async_to_sync(lambda: async_tile_stream_generator())
            ),
            content_type=ServerSentEventRenderer.media_type,
        )
        return response

    def _get_layout_size_from_request(self, request: Request) -> str:
        """Extract layout size parameter from request."""
        layout_size = "sm"

        if request and hasattr(request, "query_params"):
            # Check for both camelCase (from frontend) and snake_case (for compatibility)
            layout_size = request.query_params.get("layoutSize") or request.query_params.get("layout_size") or "sm"
            if layout_size not in ["sm", "xs"]:
                layout_size = "sm"  # fallback to sm if invalid value

        return layout_size

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
            context=self.get_serializer_context(),
        )
        return Response(serializer.data)

    @action(
        methods=["POST"],
        detail=False,
        parser_classes=[DashboardTemplateCreationJSONSchemaParser],
    )
    def create_from_template_json(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        current_url = request.headers.get("Referer")
        session_id = request.headers.get("X-Posthog-Session-Id")
        dashboard = Dashboard.objects.create(
            team_id=self.team_id,
            created_by=cast(User, request.user),
            _create_in_folder=request.data.get("_create_in_folder"),  # type: ignore
        )

        try:
            dashboard_template = DashboardTemplate(**request.data["template"])
            creation_context = request.data.get("creation_context")
            create_from_template(dashboard, dashboard_template, cast(User, request.user))

            report_user_action(
                cast(User, request.user),
                "dashboard created",
                {
                    **dashboard.get_analytics_metadata(),
                    "from_template": True,
                    "template_key": dashboard_template.template_name,
                    "duplicated": False,
                    "dashboard_id": dashboard.pk,
                    "creation_context": creation_context,
                    "$current_url": current_url,
                    "$session_id": session_id,
                },
            )
        except Exception:
            dashboard.delete()
            raise

        return Response(DashboardSerializer(dashboard, context=self.get_serializer_context()).data)


class LegacyDashboardsViewSet(DashboardsViewSet):
    param_derived_from_user_current_team = "project_id"

    def get_parents_query_dict(self) -> dict[str, Any]:
        if not self.request.user.is_authenticated or "share_token" in self.request.GET:
            return {}
        return {"team__project_id": self.project_id}


class LegacyInsightViewSet(InsightViewSet):
    param_derived_from_user_current_team = "project_id"


@receiver(model_activity_signal, sender=Dashboard)
def handle_dashboard_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name,
            type="dashboard",
        ),
    )
