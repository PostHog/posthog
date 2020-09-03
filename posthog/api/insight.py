from datetime import datetime
from distutils.util import strtobool
from typing import Any, Dict, List

from django.core.cache import cache
from django.db.models import QuerySet
from django.utils.timezone import now
from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ee.clickhouse.models.action import query_action
from posthog.celery import update_cache_item_task
from posthog.constants import DATE_FROM, FROM_DASHBOARD, INSIGHT, OFFSET, TRENDS_STICKINESS
from posthog.decorators import FUNNEL_ENDPOINT, TRENDS_ENDPOINT, cached_function
from posthog.models import DashboardItem, Filter
from posthog.models.action import Action
from posthog.queries import paths, retention, sessions, stickiness, trends
from posthog.utils import generate_cache_key, request_to_date_query


class InsightSerializer(serializers.ModelSerializer):
    result = serializers.SerializerMethodField()

    class Meta:
        model = DashboardItem
        fields = [
            "id",
            "name",
            "filters",
            "order",
            "type",
            "deleted",
            "dashboard",
            "layouts",
            "color",
            "last_refresh",
            "refreshing",
            "result",
            "created_at",
            "saved",
            "created_by",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> DashboardItem:

        request = self.context["request"]
        team = request.user.team_set.get()
        validated_data.pop("last_refresh", None)  # last_refresh sometimes gets sent if dashboard_item is duplicated

        if not validated_data.get("dashboard", None):
            dashboard_item = DashboardItem.objects.create(team=team, created_by=request.user, **validated_data)
            return dashboard_item
        elif validated_data["dashboard"].team == team:
            filter_data = validated_data.pop("filters", None)
            filters = Filter(data=filter_data) if filter_data else None
            dashboard_item = DashboardItem.objects.create(
                team=team, last_refresh=now(), filters=filters.to_dict() if filters else {}, **validated_data
            )
            return dashboard_item
        else:
            raise serializers.ValidationError("Dashboard not found")

    def get_result(self, dashboard_item: DashboardItem):
        if not dashboard_item.filters:
            return None
        filter = Filter(data=dashboard_item.filters)
        cache_key = generate_cache_key(filter.toJSON() + "_" + str(dashboard_item.team_id))
        result = cache.get(cache_key)
        if not result or result.get("task_id", None):
            return None
        return result["result"]


class InsightViewSet(viewsets.ModelViewSet):
    queryset = DashboardItem.objects.all()
    serializer_class = InsightSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":  # type: ignore
            queryset = queryset.filter(deleted=False)
            queryset = self._filter_request(self.request, queryset)

        order = self.request.GET.get("order", None)
        if order:
            queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by("order")

        return queryset.filter(team=self.request.user.team_set.get())

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "saved":
                queryset = queryset.filter(saved=bool(strtobool(str(request.GET["saved"]))))
            elif key == "user":
                queryset = queryset.filter(created_by=request.user)
            elif key == INSIGHT:
                queryset = queryset.filter(filters__insight=request.GET[INSIGHT])

        return queryset

    # ******************************************
    # Calculated Insight Endpoints
    # /insight/trend
    # /insight/session
    # /insight/funnel
    # /insight/retention
    # /insight/path
    #
    # Request parameteres and caching are handled here and passed onto respective .queries classes
    # ******************************************

    # ******************************************
    # /insight/trend
    #
    # params:
    # - from_dashboard: (string) determines trend is being retrieved from dashboard item to update dashboard_item metadata
    # - shown_as: (string: Volume, Stickiness) specifies the trend aggregation type
    # - **shared filter types
    # ******************************************
    @action(methods=["GET"], detail=False)
    def trend(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        result = self._calculate_trends(request)
        action = Action.objects.get(pk=6)
        print(len(query_action(action)))
        return Response(result)

    @cached_function(cache_type=TRENDS_ENDPOINT)
    def _calculate_trends(self, request: request.Request) -> List[Dict[str, Any]]:
        team = request.user.team_set.get()
        filter = Filter(request=request)
        if filter.shown_as == TRENDS_STICKINESS:
            result = stickiness.Stickiness().run(filter, team)
        else:
            result = trends.Trends().run(filter, team)

        self._refresh_dashboard(request=request)

        return result

    # ******************************************
    # /insight/session
    #
    # params:
    # - session: (string: avg, dist) specifies session type
    # - offset: (number) offset query param for paginated list of user sessions
    # - **shared filter types
    # ******************************************
    @action(methods=["GET"], detail=False)
    def session(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        team = self.request.user.team_set.get()

        filter = Filter(request=request)
        result: Dict[str, Any] = {"result": sessions.Sessions().run(filter, team)}

        # add pagination
        if filter.session_type is None:
            offset = filter.offset + 50
            if len(result["result"]) > 49:
                date_from = result["result"][0]["start_time"].isoformat()
                result.update({OFFSET: offset})
                result.update({DATE_FROM: date_from})
        return Response(result)

    # ******************************************
    # /insight/funnel
    # The funnel endpoint is asynchronously processed. When a request is received, the endpoint will
    # call an async task with an id that can be continually polled for 3 minutes.
    #
    # params:
    # - refresh: (dict) specifies cache to force refresh or poll
    # - from_dashboard: (dict) determines funnel is being retrieved from dashboard item to update dashboard_item metadata
    # - **shared filter types
    # ******************************************
    @action(methods=["GET"], detail=False)
    def funnel(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        team = request.user.team_set.get()
        refresh = request.GET.get("refresh", None)

        filter = Filter(request=request)
        cache_key = generate_cache_key("{}_{}".format(filter.toJSON(), team.pk))
        result = {"loading": True}

        if refresh:
            cache.delete(cache_key)
        else:
            cached_result = cache.get(cache_key)
            if cached_result:
                task_id = cached_result.get("task_id", None)
                if not task_id:
                    return Response(cached_result["result"])
                else:
                    return Response(result)

        payload = {"filter": filter.toJSON(), "team_id": team.pk}

        task = update_cache_item_task.delay(cache_key, FUNNEL_ENDPOINT, payload)
        task_id = task.id
        cache.set(cache_key, {"task_id": task_id}, 180)  # task will be live for 3 minutes

        self._refresh_dashboard(request=request)

        return Response(result)

    # ******************************************
    # /insight/retention
    # params:
    # - start_entity: (dict) specifies id and type of the entity to focus retention on
    # - **shared filter types
    # ******************************************
    @action(methods=["GET"], detail=False)
    def retention(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        team = request.user.team_set.get()
        filter = Filter(request=request)
        filter._date_from = "-11d"
        result = retention.Retention().run(filter, team)
        return Response({"data": result})

    # ******************************************
    # /insight/path
    # params:
    # - start: (string) specifies the name of the starting property or element
    # - request_type: (string: $pageview, $autocapture, $screen, custom_event) specifies the path type
    # - **shared filter types
    # ******************************************
    @action(methods=["GET"], detail=False)
    def path(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        team = request.user.team_set.get()
        filter = Filter(request=request)
        resp = paths.Paths().run(filter=filter, team=team)
        return Response(resp)

    # Checks if a dashboard id has been set and if so, update the refresh date
    def _refresh_dashboard(self, request) -> None:
        dashboard_id = request.GET.get(FROM_DASHBOARD, None)
        if dashboard_id:
            DashboardItem.objects.filter(pk=dashboard_id).update(last_refresh=datetime.now())
