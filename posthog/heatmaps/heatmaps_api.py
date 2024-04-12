from datetime import datetime, timedelta
from typing import Any

from rest_framework import viewsets, request, response, serializers, status

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import TemporaryTokenAuthentication
from posthog.hogql.ast import Constant
from posthog.hogql.base import Expr
from posthog.hogql.query import execute_hogql_query
from posthog.rate_limit import ClickHouseSustainedRateThrottle, ClickHouseBurstRateThrottle


class HeatmapResponseItemSerializer(serializers.Serializer):
    count = serializers.IntegerField(required=True)
    pointer_y = serializers.IntegerField(required=True)
    pointer_relative_x = serializers.FloatField(required=True)
    pointer_target_fixed = serializers.BooleanField(required=True)


def default_start_date():
    return (datetime.now() - timedelta(days=7)).date()


class HeatmapsRequestSerializer(serializers.Serializer):
    viewport_min_width = serializers.IntegerField(required=False)
    viewport_max_width = serializers.IntegerField(required=False)
    type = serializers.CharField(required=False)
    date_from = serializers.DateField(required=False, default=default_start_date)
    date_to = serializers.DateField(required=False)
    url_exact = serializers.CharField(required=False)
    url_pattern = serializers.CharField(required=False)


class HeatmapsResponseSerializer(serializers.Serializer):
    results = HeatmapResponseItemSerializer(many=True)


class HeatmapViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    filter_rewrite_rules = {"team_id": "group__team_id"}

    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = HeatmapsResponseSerializer

    authentication_classes = [TemporaryTokenAuthentication]

    def get_queryset(self):
        return None

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        request_serializer = HeatmapsRequestSerializer(data=request.query_params)
        request_serializer.is_valid(raise_exception=True)

        placeholders: dict[str, Expr] = {
            "team_id": Constant(value=self.team.pk),
            "date_from": Constant(value=request_serializer.validated_data["date_from"]),
        }
        if request_serializer.validated_data.get("viewport_min_width", None):
            placeholders["vp_min_w"] = Constant(value=request_serializer.validated_data["viewport_min_width"])
        if request_serializer.validated_data.get("viewport_max_width", None):
            placeholders["vp_max_w"] = Constant(value=request_serializer.validated_data["viewport_max_width"])
        if request_serializer.validated_data.get("date_to", None):
            placeholders["date_to"] = Constant(value=request_serializer.validated_data["date_to"])
        if request_serializer.validated_data.get("url_exact", None):
            placeholders["url_exact"] = Constant(value=request_serializer.validated_data["url_exact"])
        if request_serializer.validated_data.get("url_pattern", None):
            placeholders["url_pattern"] = Constant(value=request_serializer.validated_data["url_pattern"])

        q = """
            select *, count() as cnt
            from (
                     select pointer_target_fixed, round((x / viewport_width), 2) as relative_client_x,
                            y * scale_factor                  as client_y
                     from heatmaps
                     where 1=1
                     {date_from_predicate}
                    {date_to_predicate}
                    {viewport_min_width_predicate}
                    {viewport_max_width_predicate}
                    {url_exact_predicate}
                    {url_pattern_predicate}
                     {team_id_predicate}
                     )
            group by `pointer_target_fixed`, relative_client_x, client_y
            """.format(
            # required
            date_from_predicate="and timestamp >= {date_from}",
            team_id_predicate="and team_id = {team_id}",
            # optional
            date_to_predicate="and timestamp <= {date_to} + interval 1 day"
            if request_serializer.validated_data.get("date_to", None)
            else "",
            viewport_min_width_predicate="and viewport_width >= ceil({vp_min_w} / 16)"
            if request_serializer.validated_data.get("viewport_min_width", None)
            else "",
            viewport_max_width_predicate="and viewport_width <= ceil({vp_max_w} / 16)"
            if request_serializer.validated_data.get("viewport_max_width", None)
            else "",
            url_exact_predicate="and current_url = {url_exact}"
            if request_serializer.validated_data.get("url_exact", None)
            else "",
            url_pattern_predicate="and current_url like {url_pattern}"
            if request_serializer.validated_data.get("url_pattern", None)
            else "",
        )

        doohickies = execute_hogql_query(
            query=q,
            placeholders=placeholders,
            team=self.team,
        )

        data = [
            {
                "pointer_target_fixed": item[0],
                "pointer_relative_x": item[1],
                "pointer_y": item[2],
                "count": item[3],
            }
            for item in doohickies.results or []
        ]

        response_serializer = HeatmapsResponseSerializer(data={"results": data})
        response_serializer.is_valid(raise_exception=True)
        return response.Response(response_serializer.data, status=status.HTTP_200_OK)


class LegacyHeatmapViewSet(HeatmapViewSet):
    derive_current_team_from_user_only = True
