import json
from functools import lru_cache
from typing import Any, Dict, List, Optional, Type

import structlog
from django.db.models import Count, OuterRef, QuerySet, Subquery
from django.db.models.query_utils import Q
from django.http import HttpResponse
from django.utils.text import slugify
from django.utils.timezone import now
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse
from rest_framework import exceptions, request, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers
from sentry_sdk import capture_exception

from ee.clickhouse.queries.funnels import ClickhouseFunnelTimeToConvert, ClickhouseFunnelTrends
from ee.clickhouse.queries.funnels.utils import get_funnel_order_class
from ee.clickhouse.queries.paths.paths import ClickhousePaths
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from posthog.api.documentation import extend_schema
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.insight_serializers import (
    FunnelSerializer,
    FunnelStepsResultsSerializer,
    TrendResultsSerializer,
    TrendSerializer,
)
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import format_paginated_url
from posthog.constants import (
    BREAKDOWN_VALUES_LIMIT,
    INSIGHT,
    INSIGHT_FUNNELS,
    INSIGHT_PATHS,
    INSIGHT_STICKINESS,
    PATHS_INCLUDE_EVENT_TYPES,
    TRENDS_STICKINESS,
    FunnelVizType,
)
from posthog.decorators import cached_function
from posthog.helpers.multi_property_breakdown import protect_old_clients_from_multi_property_default
from posthog.models import DashboardTile, Filter, Insight, Team, User
from posthog.models.activity_logging.activity_log import (
    ActivityPage,
    Change,
    Detail,
    changes_between,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.serializers import ActivityLogSerializer
from posthog.models.dashboard import Dashboard
from posthog.models.filters import RetentionFilter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.insight import InsightViewed, generate_insight_cache_key
from posthog.models.utils import UUIDT
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.retention import Retention
from posthog.queries.stickiness import Stickiness
from posthog.queries.util import get_earliest_timestamp
from posthog.settings import SITE_URL
from posthog.tasks.update_cache import update_insight_cache
from posthog.utils import (
    format_query_params_absolute_url,
    get_safe_cache,
    relative_date_parse,
    should_refresh,
    str_to_bool,
)

logger = structlog.get_logger(__name__)


def log_insight_activity(
    activity: str,
    insight: Insight,
    insight_id: int,
    insight_short_id: str,
    organization_id: UUIDT,
    team_id: int,
    user: User,
    changes: Optional[List[Change]] = None,
) -> None:
    """
    Insight id and short_id are passed separately as some activities (like delete) alter the Insight instance

    The experiments feature creates insights without a name, this does not log those
    """

    insight_name: Optional[str] = insight.name if insight.name else insight.derived_name
    if insight_name:
        log_activity(
            organization_id=organization_id,
            team_id=team_id,
            user=user,
            item_id=insight_id,
            scope="Insight",
            activity=activity,
            detail=Detail(name=insight_name, changes=changes, short_id=insight_short_id),
        )


class InsightBasicSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    """
    Simplified serializer to speed response times when loading large amounts of objects.
    """

    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Insight
        fields = [
            "id",
            "short_id",
            "name",
            "filters",
            "dashboards",
            "description",
            "last_refresh",
            "refreshing",
            "saved",
            "tags",
            "updated_at",
            "created_by",
            "created_at",
            "last_modified_at",
        ]
        read_only_fields = ("short_id", "updated_at", "last_refresh", "refreshing")

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["filters"] = instance.dashboard_filters()
        return representation


class InsightSerializer(InsightBasicSerializer):
    result = serializers.SerializerMethodField()
    last_refresh = serializers.SerializerMethodField(
        read_only=True,
        help_text="""
    The datetime this insight's results were generated.
    If added to one or more dashboards the insight can be refreshed separately on each.
    Returns the appropriate last_refresh datetime for the context the insight is viewed in
    (see from_dashboard query parameter).
    """,
    )
    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)
    effective_privilege_level = serializers.SerializerMethodField()
    timezone = serializers.SerializerMethodField(help_text="The timezone this chart is displayed in.")
    dashboards = serializers.PrimaryKeyRelatedField(
        help_text="A dashboard ID for each of the dashboards that this insight is displayed on.",
        many=True,
        required=False,
        queryset=Dashboard.objects.filter(deleted=False),
    )
    filters_hash = serializers.CharField(
        read_only=True,
        help_text="""A hash of the filters that generate this insight.
        Used as a cache key for this result.
        A different hash will be returned if loading the insight on a dashboard that has filters.""",
    )

    class Meta:
        model = Insight
        fields = [
            "id",
            "short_id",
            "name",
            "derived_name",
            "filters",
            "filters_hash",
            "order",
            "deleted",
            "dashboards",
            "last_refresh",
            "refreshing",
            "result",
            "created_at",
            "created_by",
            "description",
            "updated_at",
            "tags",
            "favorited",
            "saved",
            "last_modified_at",
            "last_modified_by",
            "is_sample",
            "effective_restriction_level",
            "effective_privilege_level",
            "timezone",
        ]
        read_only_fields = (
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
            "short_id",
            "updated_at",
            "is_sample",
            "effective_restriction_level",
            "effective_privilege_level",
            "timezone",
            "refreshing",
        )

    @lru_cache(maxsize=1)  # each serializer instance should only deal with one insight/tile combo
    def dashboard_tile_from_context(self, insight: Insight, dashboard: Optional[Dashboard]) -> Optional[DashboardTile]:
        dashboard_tile: Optional[DashboardTile] = None
        if dashboard:
            dashboard_tile = DashboardTile.objects.filter(insight=insight, dashboard=dashboard).first()

        return dashboard_tile

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Insight:
        request = self.context["request"]
        team = Team.objects.get(id=self.context["team_id"])
        tags = validated_data.pop("tags", None)  # tags are created separately as global tag relationships

        created_by = validated_data.pop("created_by", request.user)
        dashboards = validated_data.pop("dashboards", None)

        insight = Insight.objects.create(
            team=team, created_by=created_by, last_modified_by=request.user, **validated_data
        )

        if dashboards is not None:
            for dashboard in Dashboard.objects.filter(id__in=[d.id for d in dashboards]).all():
                if dashboard.team != insight.team:
                    raise serializers.ValidationError("Dashboard not found")

                DashboardTile.objects.create(insight=insight, dashboard=dashboard, last_refresh=now())
                insight.last_refresh = now()  # set last refresh if the insight is on at least one dashboard

        # Manual tag creation since this create method doesn't call super()
        self._attempt_set_tags(tags, insight)

        log_insight_activity(
            activity="created",
            insight=insight,
            insight_id=insight.id,
            insight_short_id=insight.short_id,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=team.id,
            user=self.context["request"].user,
        )

        return insight

    def update(self, instance: Insight, validated_data: Dict, **kwargs) -> Insight:
        try:
            before_update = Insight.objects.get(pk=instance.id)
        except Insight.DoesNotExist:
            before_update = None

        # Remove is_sample if it's set as user has altered the sample configuration
        validated_data["is_sample"] = False
        if validated_data.keys() & Insight.MATERIAL_INSIGHT_FIELDS:
            instance.last_modified_at = now()
            instance.last_modified_by = self.context["request"].user

        if validated_data.get("deleted", False):
            DashboardTile.objects.filter(insight__id=instance.id).delete()
        else:
            dashboards = validated_data.pop("dashboards", None)
            if dashboards is not None:
                old_dashboard_ids = [tile.dashboard_id for tile in instance.dashboardtile_set.all()]
                new_dashboard_ids = [d.id for d in dashboards]

                ids_to_add = [id for id in new_dashboard_ids if id not in old_dashboard_ids]
                ids_to_remove = [id for id in old_dashboard_ids if id not in new_dashboard_ids]

                for dashboard in Dashboard.objects.filter(id__in=ids_to_add):
                    if dashboard.team != instance.team:
                        raise serializers.ValidationError("Dashboard not found")
                    DashboardTile.objects.create(insight=instance, dashboard=dashboard)

                if ids_to_remove:
                    DashboardTile.objects.filter(dashboard_id__in=ids_to_remove, insight=instance).delete()

        updated_insight = super().update(instance, validated_data)

        changes = changes_between("Insight", previous=before_update, current=updated_insight)

        log_insight_activity(
            activity="updated",
            insight=updated_insight,
            insight_id=updated_insight.id,
            insight_short_id=updated_insight.short_id,
            organization_id=self.context["request"].user.current_organization_id,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            changes=changes,
        )

        return updated_insight

    def get_result(self, insight: Insight):
        if not insight.filters:
            return None

        dashboard = self.context.get("dashboard", None)

        if should_refresh(self.context["request"]):
            return update_insight_cache(insight, dashboard)

        cache_key = insight.filters_hash
        if dashboard is not None:
            dashboard_tile = self.dashboard_tile_from_context(insight, dashboard)
            if dashboard_tile is not None:
                cache_key = dashboard_tile.filters_hash
                if cache_key is None:
                    # the DashboardTile hasn't had a filters_hash added yet
                    # TODO need to run a migration after 0229 to ensure all tiles have a filters hash
                    generated_filters_hash = generate_insight_cache_key(insight, dashboard)
                    dashboard_tile.filters_hash = generated_filters_hash
                    dashboard_tile.save(update_fields=["filters_hash"])
                    cache_key = generated_filters_hash

        self.context.update({"filters_hash": cache_key})
        result = get_safe_cache(cache_key)
        if not result or result.get("task_id", None):
            return None
        # Data might not be defined if there is still cached results from before moving from 'results' to 'data'
        return result.get("result")

    def get_timezone(self, insight: Insight):
        if should_refresh(self.context["request"]):
            return insight.team.timezone
        result = get_safe_cache(insight.filters_hash)
        if not result or result.get("task_id", None):
            return None
        return result.get("timezone")

    def get_last_refresh(self, insight: Insight):
        if should_refresh(self.context["request"]):
            return now()

        dashboard_tile = self.dashboard_tile_from_context(insight, self.context.get("dashboard", None))

        result = self.get_result(insight)
        if result is not None:
            if dashboard_tile:
                return dashboard_tile.last_refresh
            else:
                return insight.last_refresh

        if dashboard_tile is not None:
            if dashboard_tile.last_refresh is not None:
                dashboard_tile.last_refresh = None
                dashboard_tile.save(update_fields=["last_refresh"])
        else:
            if insight.last_refresh is not None:
                # Update last_refresh without updating "updated_at" (insight edit date)
                insight.last_refresh = None
                insight.save(update_fields=["last_refresh"])
        return None

    def get_effective_privilege_level(self, insight: Insight) -> Dashboard.PrivilegeLevel:
        return insight.get_effective_privilege_level(self.context["request"].user.id)

    def to_representation(self, instance: Insight):
        representation = super().to_representation(instance)

        dashboard: Optional[Dashboard] = self.context.get("dashboard")
        representation["filters"] = instance.dashboard_filters(dashboard=dashboard)

        context_cache_key = self.context.get("filters_hash")
        representation["filters_hash"] = context_cache_key if context_cache_key is not None else instance.filters_hash

        return representation


class InsightViewSet(TaggedItemViewSetMixin, StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Insight.objects.all()
    serializer_class = InsightSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.CSVRenderer,)
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id", "created_by"]
    include_in_docs = True

    retention_query_class = Retention
    stickiness_query_class = Stickiness

    def get_serializer_class(self) -> Type[serializers.BaseSerializer]:

        if (self.action == "list" or self.action == "retrieve") and str_to_bool(
            self.request.query_params.get("basic", "0"),
        ):
            return InsightBasicSerializer
        return super().get_serializer_class()

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()

        if not self.action.endswith("update"):
            # Soft-deleted insights can be brought back with a PATCH request
            queryset = queryset.filter(deleted=False)

        queryset = queryset.prefetch_related(
            "dashboards", "dashboards__created_by", "dashboards__team", "dashboards__team__organization",
        )
        queryset = queryset.select_related("created_by", "last_modified_by", "team")
        if self.action == "list":
            queryset = queryset.filter(deleted=False)
            queryset = self._filter_request(self.request, queryset)

        order = self.request.GET.get("order", None)
        if order:
            if order == "-my_last_viewed_at":
                queryset = self._annotate_with_my_last_viewed_at(queryset).order_by("-my_last_viewed_at")
            else:
                queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by("order")

        return queryset

    def _annotate_with_my_last_viewed_at(self, queryset: QuerySet) -> QuerySet:
        if self.request.user.is_authenticated:
            insight_viewed = InsightViewed.objects.filter(
                team=self.team, user=self.request.user, insight_id=OuterRef("id")
            )
            return queryset.annotate(my_last_viewed_at=Subquery(insight_viewed.values("last_viewed_at")[:1]))
        raise exceptions.NotAuthenticated()

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "saved":
                if str_to_bool(request.GET["saved"]):
                    queryset = queryset.annotate(dashboards_count=Count("dashboards"))
                    queryset = queryset.filter(Q(saved=True) | Q(dashboards_count__gte=1))
                else:
                    queryset = queryset.filter(Q(saved=False))

            elif key == "my_last_viewed":
                if str_to_bool(request.GET["my_last_viewed"]):
                    queryset = self._annotate_with_my_last_viewed_at(queryset).filter(my_last_viewed_at__isnull=False)
            elif key == "user":
                queryset = queryset.filter(created_by=request.user)
            elif key == "favorited":
                queryset = queryset.filter(Q(favorited=True))
            elif key == "date_from":
                queryset = queryset.filter(last_modified_at__gt=relative_date_parse(request.GET["date_from"]))
            elif key == "date_to":
                queryset = queryset.filter(last_modified_at__lt=relative_date_parse(request.GET["date_to"]))
            elif key == INSIGHT:
                queryset = queryset.filter(filters__insight=request.GET[INSIGHT])
            elif key == "search":
                queryset = queryset.filter(
                    Q(name__icontains=request.GET["search"]) | Q(derived_name__icontains=request.GET["search"])
                )
        return queryset

    def retrieve(self, request, *args, **kwargs):
        """
        When loading an insight for a dashboard pass a `from_dashboard` query parameter containing the dashboard ID

        e.g. `"/api/projects/{team_id}/insights/{insight_id}?from_dashboard={dashboard_id}"`

        Insights can be added to more than one dashboard, this allows the insight to be loaded in the correct context.

        Using the correct cache and enriching the response with dashboard specific config (e.g. layouts or colors)
        """
        instance = self.get_object()
        serializer_context = self.get_serializer_context()

        dashboard_tile: Optional[DashboardTile] = None
        dashboard_id = request.query_params.get("from_dashboard", None)
        if dashboard_id is not None:
            dashboard_tile = (
                DashboardTile.objects.filter(dashboard__id=dashboard_id, insight__id=instance.id)
                .select_related("dashboard")
                .first()
            )

        if dashboard_tile is not None:
            # context is used in the to_representation method to report filters used
            serializer_context.update({"dashboard": dashboard_tile.dashboard})

        serialized_data = self.get_serializer(instance, context=serializer_context).data

        if dashboard_tile is not None:
            serialized_data["color"] = dashboard_tile.color
            layouts = dashboard_tile.layouts
            # workaround because DashboardTiles layouts were migrated as stringified JSON :/
            if isinstance(layouts, str):
                layouts = json.loads(layouts)

            serialized_data["layouts"] = layouts

        return Response(serialized_data)

    # ******************************************
    # Calculated Insight Endpoints
    # /projects/:id/insights/trend
    # /projects/:id/insights/funnel
    # /projects/:id/insights/retention
    # /projects/:id/insights/path
    #
    # Request parameters and caching are handled here and passed onto respective .queries classes
    # ******************************************

    # ******************************************
    # /projects/:id/insights/trend
    #
    # params:
    # - from_dashboard: (string) determines trend is being retrieved from dashboard item to update dashboard_item metadata
    # - shown_as: (string: Volume, Stickiness) specifies the trend aggregation type
    # - **shared filter types
    # ******************************************
    @extend_schema(
        request=TrendSerializer,
        methods=["POST"],
        tags=["trend"],
        operation_id="Trends",
        responses=TrendResultsSerializer,
    )
    @action(methods=["GET", "POST"], detail=False)
    def trend(self, request: request.Request, *args: Any, **kwargs: Any):
        try:
            serializer = TrendSerializer(request=request)
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            capture_exception(e)

        result = self.calculate_trends(request)
        filter = Filter(request=request, team=self.team)
        next = (
            format_paginated_url(request, filter.offset, BREAKDOWN_VALUES_LIMIT)
            if len(result["result"]) >= BREAKDOWN_VALUES_LIMIT
            else None
        )
        if self.request.accepted_renderer.format == "csv":
            csvexport = []
            for item in result["result"]:
                line = {"series": item["action"].get("custom_name") or item["label"]}
                for index, data in enumerate(item["data"]):
                    line[item["labels"][index]] = data
                csvexport.append(line)
            renderer = csvrenderers.CSVRenderer()
            renderer.header = csvexport[0].keys()
            export = renderer.render(csvexport)
            if request.GET.get("export_insight_id"):
                export = "{}/insights/{}/\n".format(SITE_URL, request.GET["export_insight_id"]).encode() + export

            response = HttpResponse(export)
            response[
                "Content-Disposition"
            ] = 'attachment; filename="{name} ({date_from} {date_to}) from PostHog.csv"'.format(
                name=slugify(request.GET.get("export_name", "export")),
                date_from=filter.date_from.strftime("%Y-%m-%d -") if filter.date_from else "up until",
                date_to=filter.date_to.strftime("%Y-%m-%d"),
            )
            return response
        return Response({**result, "next": next})

    @cached_function
    def calculate_trends(self, request: request.Request) -> Dict[str, Any]:
        team = self.team
        filter = Filter(request=request, team=self.team)

        if filter.insight == INSIGHT_STICKINESS or filter.shown_as == TRENDS_STICKINESS:
            stickiness_filter = StickinessFilter(
                request=request, team=team, get_earliest_timestamp=get_earliest_timestamp
            )
            result = self.stickiness_query_class().run(stickiness_filter, team)
        else:
            trends_query = ClickhouseTrends()
            result = trends_query.run(filter, team)

        return {"result": result, "timezone": team.timezone}

    # ******************************************
    # /projects/:id/insights/funnel
    # The funnel endpoint is asynchronously processed. When a request is received, the endpoint will
    # call an async task with an id that can be continually polled for 3 minutes.
    #
    # params:
    # - refresh: (dict) specifies cache to force refresh or poll
    # - from_dashboard: (dict) determines funnel is being retrieved from dashboard item to update dashboard_item metadata
    # - **shared filter types
    # ******************************************
    @extend_schema(
        request=FunnelSerializer,
        responses=OpenApiResponse(
            response=FunnelStepsResultsSerializer,
            description="Note, if funnel_viz_type is set the response will be different.",
        ),
        methods=["POST"],
        tags=["funnel"],
        operation_id="Funnels",
    )
    @action(methods=["GET", "POST"], detail=False)
    def funnel(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        try:
            serializer = FunnelSerializer(request=request)
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            capture_exception(e)

        funnel = self.calculate_funnel(request)

        funnel["result"] = protect_old_clients_from_multi_property_default(request.data, funnel["result"])

        return Response(funnel)

    @cached_function
    def calculate_funnel(self, request: request.Request) -> Dict[str, Any]:
        team = self.team
        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS}, team=self.team)

        if filter.funnel_viz_type == FunnelVizType.TRENDS:
            return {
                "result": ClickhouseFunnelTrends(team=team, filter=filter).run(),
                "timezone": team.timezone,
            }
        elif filter.funnel_viz_type == FunnelVizType.TIME_TO_CONVERT:
            return {
                "result": ClickhouseFunnelTimeToConvert(team=team, filter=filter).run(),
                "timezone": team.timezone,
            }
        else:
            funnel_order_class = get_funnel_order_class(filter)
            return {"result": funnel_order_class(team=team, filter=filter).run(), "timezone": team.timezone}

    # ******************************************
    # /projects/:id/insights/retention
    # params:
    # - start_entity: (dict) specifies id and type of the entity to focus retention on
    # - **shared filter types
    # ******************************************
    @action(methods=["GET"], detail=False)
    def retention(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        result = self.calculate_retention(request)
        return Response(result)

    @cached_function
    def calculate_retention(self, request: request.Request) -> Dict[str, Any]:
        team = self.team
        data = {}
        if not request.GET.get("date_from"):
            data.update({"date_from": "-11d"})
        filter = RetentionFilter(data=data, request=request, team=self.team)
        base_uri = request.build_absolute_uri("/")
        result = self.retention_query_class(base_uri=base_uri).run(filter, team)
        return {"result": result, "timezone": team.timezone}

    # ******************************************
    # /projects/:id/insights/path
    # params:
    # - start: (string) specifies the name of the starting property or element
    # - request_type: (string: $pageview, $autocapture, $screen, custom_event) specifies the path type
    # - **shared filter types
    # ******************************************
    @action(methods=["GET", "POST"], detail=False)
    def path(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        result = self.calculate_path(request)
        return Response(result)

    @cached_function
    def calculate_path(self, request: request.Request) -> Dict[str, Any]:
        team = self.team
        filter = PathFilter(request=request, data={"insight": INSIGHT_PATHS}, team=self.team)

        funnel_filter = None
        funnel_filter_data = request.GET.get("funnel_filter") or request.data.get("funnel_filter")
        if funnel_filter_data:
            if isinstance(funnel_filter_data, str):
                funnel_filter_data = json.loads(funnel_filter_data)
            funnel_filter = Filter(data={"insight": INSIGHT_FUNNELS, **funnel_filter_data}, team=self.team)

        #  backwards compatibility
        if filter.path_type:
            filter = filter.with_data({PATHS_INCLUDE_EVENT_TYPES: [filter.path_type]})
        resp = ClickhousePaths(filter=filter, team=team, funnel_filter=funnel_filter).run()

        return {"result": resp, "timezone": team.timezone}

    # ******************************************
    # /projects/:id/insights/:short_id/viewed
    # Creates or updates an InsightViewed object for the user/insight combo
    # ******************************************
    @action(methods=["POST"], detail=True)
    def viewed(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        InsightViewed.objects.update_or_create(
            team=self.team, user=request.user, insight=self.get_object(), defaults={"last_viewed_at": now()}
        )
        return Response(status=status.HTTP_201_CREATED)

    @action(methods=["GET"], url_path="activity", detail=False)
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))
        activity_page = load_activity(scope="Insight", team_id=self.team_id)
        return self._return_activity_page(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True)
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]
        if not Insight.objects.filter(id=item_id, team_id=self.team_id).exists():
            return Response("", status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(scope="Insight", team_id=self.team_id, item_id=item_id, limit=limit, page=page)
        return self._return_activity_page(activity_page, limit, page, request)

    @staticmethod
    def _return_activity_page(activity_page: ActivityPage, limit: int, page: int, request: request.Request) -> Response:
        return Response(
            {
                "results": ActivityLogSerializer(activity_page.results, many=True,).data,
                "next": format_query_params_absolute_url(request, page + 1, limit, offset_alias="page")
                if activity_page.has_next
                else None,
                "previous": format_query_params_absolute_url(request, page - 1, limit, offset_alias="page")
                if activity_page.has_previous
                else None,
                "total_count": activity_page.total_count,
            },
            status=status.HTTP_200_OK,
        )


class LegacyInsightViewSet(InsightViewSet):
    legacy_team_compatibility = True
