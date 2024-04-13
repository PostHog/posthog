from datetime import datetime, timedelta, date
from typing import Any, Dict, List

from rest_framework import viewsets, request, response, serializers, status

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import TemporaryTokenAuthentication
from posthog.hogql import ast
from posthog.hogql.ast import Constant
from posthog.hogql.base import Expr
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.rate_limit import ClickHouseSustainedRateThrottle, ClickHouseBurstRateThrottle
from posthog.schema import HogQLQueryResponse
from posthog.utils import relative_date_parse_with_delta_mapping

DEFAULT_QUERY = """
            select pointer_target_fixed, relative_client_x, client_y, {aggregation_count}
            from (
                     select
                        distinct_id,
                        pointer_target_fixed,
                        round((x / viewport_width), 2) as relative_client_x,
                        y * scale_factor as client_y
                     from heatmaps
                     where {predicates}
                )
            group by `pointer_target_fixed`, relative_client_x, client_y
            -- hogql enforces a limit (and only allows a max of 10000) but we don't really want one
            -- see https://github.com/PostHog/posthog/blob/715a8b924e7c5dca7ae986bfdba6072b3999dbed/posthog/hogql/constants.py#L33
            limit 10000000
            """

SCROLL_DEPTH_QUERY = """
SELECT
    bucket,
    cnt as bucket_count,
    sum(cnt) OVER (ORDER BY bucket DESC) AS cumulative_count
FROM (
    SELECT
        intDiv(scroll_y, 100) * 100 as bucket,
        {aggregation_count} as cnt
    FROM (
        SELECT
           distinct_id, (y + viewport_height) * scale_factor as scroll_y
        FROM heatmaps
        WHERE {predicates}
    )
    GROUP BY bucket
)
ORDER BY bucket
-- hogql enforces a limit (and only allows a max of 10000) but we don't really want one
-- see https://github.com/PostHog/posthog/blob/715a8b924e7c5dca7ae986bfdba6072b3999dbed/posthog/hogql/constants.py#L33
limit 10000000
"""


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
    type = serializers.CharField(required=False, default="click")
    date_from = serializers.CharField(required=False, default="-7d")
    date_to = serializers.DateField(required=False)
    url_exact = serializers.CharField(required=False)
    url_pattern = serializers.CharField(required=False)
    aggregation = serializers.CharField(required=False, default="total_count")

    def validate_aggregation(self, value: str) -> str:
        if value not in ["total_count", "unique_visitors"]:
            raise serializers.ValidationError("Invalid aggregation provided: {}".format(value))

        return value

    def validate_date_from(self, value) -> date:
        try:
            if isinstance(value, str):
                parsed_date, _, _ = relative_date_parse_with_delta_mapping(value, self.context["team"].timezone_info)
                return parsed_date.date()
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            else:
                raise serializers.ValidationError("Invalid date_from provided: {}".format(value))
        except Exception:
            raise serializers.ValidationError("Error parsing provided date_from: {}".format(value))

    def validate(self, values) -> Dict:
        url_exact = values.get("url_exact", None)
        url_pattern = values.get("url_pattern", None)
        if isinstance(url_exact, str) and isinstance(url_pattern, str):
            if url_exact == url_pattern:
                values.pop("url_pattern")
            else:
                values.pop("url_exact")

        return values


class HeatmapsResponseSerializer(serializers.Serializer):
    results = HeatmapResponseItemSerializer(many=True)


class HeatmapsScrollDepthResponseSerializer(serializers.Serializer):
    results = serializers.ListField(child=serializers.DictField())


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

        aggregation = request_serializer.validated_data.pop("aggregation")

        placeholders: dict[str, Expr] = {k: Constant(value=v) for k, v in request_serializer.validated_data.items()}

        is_scrolldepth_query = placeholders.get("type", None) == Constant(value="scrolldepth")
        raw_query = SCROLL_DEPTH_QUERY if is_scrolldepth_query else DEFAULT_QUERY

        aggregation_value = "count(*) as cnt" if aggregation == "total_count" else "count(distinct distinct_id) as cnt"
        if is_scrolldepth_query:
            aggregation_value = "count(*)" if aggregation == "total_count" else "count(distinct distinct_id)"
        aggregation_count = parse_expr(aggregation_value)

        exprs = self._predicate_expressions(placeholders)

        stmt = parse_select(raw_query, {"aggregation_count": aggregation_count, "predicates": ast.And(exprs=exprs)})

        doohickies = execute_hogql_query(
            query=stmt,
            team=self.team,
        )

        if is_scrolldepth_query:
            return self._return_scroll_depth_response(doohickies)
        else:
            return self._return_heatmap_coordinates_response(doohickies)

    def _predicate_expressions(self, placeholders):
        exprs: List[ast.Expr] = []

        predicate_mapping = {
            # should always have values
            "date_from": "timestamp >= {date_from}",
            "type": "`type` = {type}",
            # optional
            "date_to": "timestamp <= {date_to} + interval 1 day",
            "viewport_width_min": "viewport_width >= ceil({viewport_width_min} / 16)",
            "viewport_width_max": "viewport_width <= ceil({viewport_width_max} / 16)",
            "url_exact": "current_url = {url_exact}",
            "url_pattern": "match(current_url, {url_pattern})",
        }

        for predicate_key in placeholders.keys():
            exprs.append(parse_expr(predicate_mapping[predicate_key], {predicate_key: placeholders[predicate_key]}))

        if len(exprs) == 0:
            raise serializers.ValidationError("must always generate some filter conditions")

        # if placeholders.get("date_to", None):
        #     exprs.append(parse_expr("timestamp <= {date_to} + interval 1 day", {"date_to": placeholders["date_to"]}))
        # if placeholders.get("viewport_width_min", None):
        #     exprs.append(
        #         parse_expr(
        #             "viewport_width >= ceil({viewport_width_min} / 16)",
        #             {"viewport_width_min": placeholders["viewport_width_min"]},
        #         )
        #     )
        # if placeholders.get("viewport_width_max", None):
        #     exprs.append(
        #         parse_expr(
        #             "viewport_width <= ceil({viewport_width_max} / 16)",
        #             {"viewport_width_max": placeholders["viewport_width_max"]},
        #         )
        #     )
        # if placeholders.get("url_exact", None):
        #     exprs.append(parse_expr("current_url = {url_exact}", {"url_exact": placeholders["url_exact"]}))
        # if placeholders.get("url_pattern", None):
        #     exprs.append(parse_expr("match(current_url, {url_pattern})", {"url_pattern": placeholders["url_pattern"]}))
        # if placeholders.get("type", None):
        #     exprs.append(parse_expr("`type` = {type}", {"type": placeholders["type"]}))
        return exprs

    def _return_heatmap_coordinates_response(self, query_response: HogQLQueryResponse) -> response.Response:
        data = [
            {
                "pointer_target_fixed": item[0],
                "pointer_relative_x": item[1],
                "pointer_y": item[2],
                "count": item[3],
            }
            for item in query_response.results or []
        ]

        response_serializer = HeatmapsResponseSerializer(data={"results": data})
        response_serializer.is_valid(raise_exception=True)
        return response.Response(response_serializer.data, status=status.HTTP_200_OK)

    def _return_scroll_depth_response(self, query_response: HogQLQueryResponse) -> response.Response:
        data = [
            {
                "scroll_depth_bucket": item[0],
                "bucket_count": item[1],
                "cumulative_count": item[2],
            }
            for item in query_response.results or []
        ]

        response_serializer = HeatmapsScrollDepthResponseSerializer(data={"results": data})
        response_serializer.is_valid(raise_exception=True)
        return response.Response(response_serializer.data, status=status.HTTP_200_OK)


class LegacyHeatmapViewSet(HeatmapViewSet):
    derive_current_team_from_user_only = True
