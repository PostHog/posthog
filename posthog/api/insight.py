from typing import Any, Dict, Type

from django.core.cache import cache
from django.db.models import QuerySet
from django.db.models.query_utils import Q
from django.utils.timezone import now
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import format_paginated_url
from posthog.celery import update_cache_item_task
from posthog.constants import (
    FROM_DASHBOARD,
    INSIGHT,
    INSIGHT_FUNNELS,
    INSIGHT_PATHS,
    INSIGHT_STICKINESS,
    TRENDS_STICKINESS,
)
from posthog.decorators import CacheType, cached_function
from posthog.helpers.multi_property_breakdown import protect_old_clients_from_multi_property_default
from posthog.models import Event, Filter, Insight, Team
from posthog.models.filters import RetentionFilter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries import paths, retention, stickiness, trends
from posthog.queries.sessions.sessions import Sessions
from posthog.tasks.update_cache import update_dashboard_item_cache
from posthog.utils import generate_cache_key, get_safe_cache, relative_date_parse, should_refresh, str_to_bool


class InsightBasicSerializer(serializers.ModelSerializer):
    """
    Simplified serializer to speed response times when loading large amounts of objects.
    """

    class Meta:
        model = Insight
        fields = [
            "id",
            "short_id",
            "name",
            "filters",
            "dashboard",
            "color",
            "description",
            "last_refresh",
            "refreshing",
            "saved",
            "updated_at",
        ]
        read_only_fields = ("short_id", "updated_at")

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError()

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["filters"] = instance.dashboard_filters()
        return representation


class InsightSerializer(InsightBasicSerializer):
    result = serializers.SerializerMethodField()
    last_refresh = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Insight
        fields = [
            "id",
            "short_id",
            "name",
            "filters",
            "filters_hash",
            "order",
            "deleted",
            "dashboard",
            "dive_dashboard",
            "layouts",
            "color",
            "last_refresh",
            "refreshing",
            "result",
            "created_at",
            "description",
            "updated_at",
            "tags",
            "favorited",
            "saved",
            "created_by",
            "is_sample",
        ]
        read_only_fields = ("created_by", "created_at", "short_id", "updated_at", "is_sample")

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Insight:
        request = self.context["request"]
        team = Team.objects.get(id=self.context["team_id"])
        validated_data.pop("last_refresh", None)  # last_refresh sometimes gets sent if dashboard_item is duplicated

        if not validated_data.get("dashboard", None) and not validated_data.get("dive_dashboard", None):
            dashboard_item = Insight.objects.create(team=team, created_by=request.user, **validated_data)
            return dashboard_item
        elif validated_data["dashboard"].team == team:
            created_by = validated_data.pop("created_by", request.user)
            dashboard_item = Insight.objects.create(
                team=team, last_refresh=now(), created_by=created_by, **validated_data
            )
            return dashboard_item
        else:
            raise serializers.ValidationError("Dashboard not found")

    def update(self, instance: Insight, validated_data: Dict, **kwargs) -> Insight:
        # Remove is_sample if it's set as user has altered the sample configuration
        validated_data["is_sample"] = False
        return super().update(instance, validated_data)

    def get_result(self, insight: Insight):
        if not insight.filters:
            return None
        if self.context["request"].GET.get("refresh"):
            return update_dashboard_item_cache(insight, None)

        result = get_safe_cache(insight.filters_hash)
        if not result or result.get("task_id", None):
            return None
        # Data might not be defined if there is still cached results from before moving from 'results' to 'data'
        return result.get("result")

    def get_last_refresh(self, insight: Insight):
        if self.context["request"].GET.get("refresh"):
            return now()

        result = self.get_result(insight)
        if result is not None:
            return insight.last_refresh
        if insight.last_refresh is not None:
            # Update last_refresh without updating "updated_at" (insight edit date)
            Insight.objects.filter(pk=insight.pk).update(last_refresh=None)
            insight.refresh_from_db()
        return None

    def to_representation(self, instance: Insight):
        representation = super().to_representation(instance)
        representation["filters"] = instance.dashboard_filters(dashboard=self.context.get("dashboard"))
        return representation


class InsightViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = Insight.objects.all()
    serializer_class = InsightSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id", "created_by"]

    def get_serializer_class(self) -> Type[serializers.BaseSerializer]:

        if (self.action == "list" or self.action == "retrieve") and str_to_bool(
            self.request.query_params.get("basic", "0"),
        ):
            return InsightBasicSerializer
        return super().get_serializer_class()

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.filter(deleted=False)
            queryset = self._filter_request(self.request, queryset)

        order = self.request.GET.get("order", None)
        if order:
            queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by("order")

        return queryset

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "saved":
                if str_to_bool(request.GET["saved"]):
                    queryset = queryset.filter(Q(saved=True) | Q(dashboard__isnull=False))
                else:
                    queryset = queryset.filter(Q(saved=False))
            elif key == "user":
                queryset = queryset.filter(created_by=request.user)
            elif key == "favorited":
                queryset = queryset.filter(Q(favorited=True))
            elif key == "date_from":
                queryset = queryset.filter(updated_at__gt=relative_date_parse(request.GET["date_from"]))
            elif key == "date_to":
                queryset = queryset.filter(updated_at__lt=relative_date_parse(request.GET["date_to"]))
            elif key == INSIGHT:
                queryset = queryset.filter(filters__insight=request.GET[INSIGHT])
            elif key == "search":
                queryset = queryset.filter(name__icontains=request.GET["search"])
        return queryset

    @action(methods=["patch"], detail=False)
    def layouts(self, request, **kwargs):
        """Dashboard item layouts."""
        queryset = self.get_queryset()
        for data in request.data["items"]:
            queryset.filter(pk=data["id"]).update(layouts=data["layouts"])
        serializer = self.get_serializer(queryset.all(), many=True)
        return Response(serializer.data)

    # ******************************************
    # Calculated Insight Endpoints
    # /projects/:id/insights/trend
    # /projects/:id/insights/session
    # /projects/:id/insights/funnel
    # /projects/:id/insights/retention
    # /projects/:id/insights/path
    #
    # Request parameteres and caching are handled here and passed onto respective .queries classes
    # ******************************************

    # ******************************************
    # /projects/:id/insights/trend
    #
    # params:
    # - from_dashboard: (string) determines trend is being retrieved from dashboard item to update dashboard_item metadata
    # - shown_as: (string: Volume, Stickiness) specifies the trend aggregation type
    # - **shared filter types
    # ******************************************
    @action(methods=["GET"], detail=False)
    def trend(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        result = self.calculate_trends(request)
        filter = Filter(request=request, team=self.team)
        next = format_paginated_url(request, filter.offset, 20) if len(result["result"]) > 20 else None
        return Response({**result, "next": next})

    @cached_function
    def calculate_trends(self, request: request.Request) -> Dict[str, Any]:
        team = self.team
        filter = Filter(request=request, team=self.team)
        if filter.insight == INSIGHT_STICKINESS or filter.shown_as == TRENDS_STICKINESS:
            earliest_timestamp_func = lambda team_id: Event.objects.earliest_timestamp(team_id)
            stickiness_filter = StickinessFilter(
                request=request, team=team, get_earliest_timestamp=earliest_timestamp_func
            )
            result = stickiness.Stickiness().run(stickiness_filter, team)
        else:
            result = trends.Trends().run(filter, team)

        self._refresh_dashboard(request=request)

        return {"result": result}

    # ******************************************
    # /projects/:id/insights/session
    #
    # params:
    # - session: (string: avg, dist) specifies session type
    # - **shared filter types
    # ******************************************
    @action(methods=["GET"], detail=False)
    def session(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        return Response(self.calculate_session(request))

    @cached_function
    def calculate_session(self, request: request.Request) -> Dict[str, Any]:
        result = Sessions().run(filter=SessionsFilter(request=request, team=self.team), team=self.team)
        return {"result": result}

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
    @action(methods=["GET", "POST"], detail=False)
    def funnel(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        funnel = self.calculate_funnel(request)

        funnel["result"] = protect_old_clients_from_multi_property_default(request.data, funnel["result"])

        return Response(funnel)

    @cached_function
    def calculate_funnel(self, request: request.Request) -> Dict[str, Any]:
        team = self.team
        refresh = should_refresh(request)

        filter = Filter(request=request, data={**request.data, "insight": INSIGHT_FUNNELS})
        cache_key = generate_cache_key(f"{filter.toJSON()}_{team.pk}")
        result = {"loading": True}

        if refresh:
            cache.delete(cache_key)
        else:
            cached_result = get_safe_cache(cache_key)
            if cached_result:
                task_id = cached_result.get("task_id", None)
                if not task_id:
                    return {"result": cached_result["result"]}
                else:
                    return {"result": result}

        payload = {"filter": filter.toJSON(), "team_id": team.pk}
        task = update_cache_item_task.delay(cache_key, CacheType.FUNNEL, payload)
        if not task.ready():
            task_id = task.id
            cache.set(cache_key, {"task_id": task_id}, 180)  # task will be live for 3 minutes

        self._refresh_dashboard(request=request)
        return {"result": result}

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
        filter = RetentionFilter(data=data, request=request)
        base_uri = request.build_absolute_uri("/")
        result = retention.Retention(base_uri=base_uri).run(filter, team)
        return {"result": result}

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
        filter = PathFilter(request=request, data={**request.data, "insight": INSIGHT_PATHS})
        resp = paths.Paths().run(filter=filter, team=team)
        return {"result": resp}

    # Checks if a dashboard id has been set and if so, update the refresh date
    def _refresh_dashboard(self, request) -> None:
        dashboard_id = request.GET.get(FROM_DASHBOARD, None)
        if dashboard_id:
            Insight.objects.filter(pk=dashboard_id).update(last_refresh=now())


class LegacyInsightViewSet(InsightViewSet):
    legacy_team_compatibility = True
