from datetime import datetime, timedelta, date
from typing import Any

from rest_framework import viewsets, request, response, serializers, status

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import TemporaryTokenAuthentication
from posthog.hogql.ast import Constant
from posthog.hogql.base import Expr
from posthog.hogql.query import execute_hogql_query
from posthog.rate_limit import ClickHouseSustainedRateThrottle, ClickHouseBurstRateThrottle
from posthog.utils import relative_date_parse_with_delta_mapping


class HeatmapResponseItemSerializer(serializers.Serializer):
    count = serializers.IntegerField(required=True)
    pointer_y = serializers.IntegerField(required=True)
    pointer_relative_x = serializers.FloatField(required=True)
    pointer_target_fixed = serializers.BooleanField(required=True)


def default_start_date():
    return (datetime.now() - timedelta(days=7)).date()


class HeatmapsRequestSerializer(serializers.Serializer):
    viewport_width_min = serializers.IntegerField(required=False)
    viewport_width_max = serializers.IntegerField(required=False)
    type = serializers.CharField(required=False)
    date_from = serializers.CharField(required=False, default="-7d")
    date_to = serializers.DateField(required=False)
    url_exact = serializers.CharField(required=False)
    url_pattern = serializers.CharField(required=False)

    def validate_date_from(self, value):
        try:
            if isinstance(value, str):
                parsed_date, _, _ = relative_date_parse_with_delta_mapping(value, self.context["team"].timezone_info)
                return parsed_date
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            else:
                raise serializers.ValidationError("Invalid date_from provided: {}".format(value))
        except Exception as e:
            raise serializers.ValidationError("Error parsing date: {}".format(e))


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
        request_serializer = HeatmapsRequestSerializer(data=request.query_params, context={"team": self.team})
        request_serializer.is_valid(raise_exception=True)

        placeholders: dict[str, Expr] = {k: Constant(value=v) for k, v in request_serializer.validated_data.items()}
        placeholders["team_id"] = Constant(value=self.team.pk)

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
                     {type_predicate}
                     {team_id_predicate}
                     )
            group by `pointer_target_fixed`, relative_client_x, client_y
            """.format(
            # required
            date_from_predicate="and timestamp >= {date_from}",
            team_id_predicate="and team_id = {team_id}",
            # optional
            date_to_predicate="and timestamp <= {date_to} + interval 1 day"
            if placeholders.get("date_to", None)
            else "",
            viewport_min_width_predicate="and viewport_width >= ceil({viewport_width_min} / 16)"
            if placeholders.get("viewport_width_min", None)
            else "",
            viewport_max_width_predicate="and viewport_width <= ceil({viewport_width_max} / 16)"
            if placeholders.get("viewport_width_max", None)
            else "",
            url_exact_predicate="and current_url = {url_exact}" if placeholders.get("url_exact", None) else "",
            url_pattern_predicate="and current_url like {url_pattern}" if placeholders.get("url_pattern", None) else "",
            type_predicate="and type = {type}" if placeholders.get("type", None) else "",
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
