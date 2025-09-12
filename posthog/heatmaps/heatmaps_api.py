from datetime import date, datetime
from typing import Any, List, Literal  # noqa: UP035

from rest_framework import request, response, serializers, status, viewsets

from posthog.schema import DateRange, HogQLFilters, HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.ast import Constant
from posthog.hogql.base import Expr
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import TemporaryTokenAuthentication
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.utils import relative_date_parse_with_delta_mapping

DEFAULT_QUERY = """
            select pointer_target_fixed, pointer_relative_x, client_y, {aggregation_count}
            from (
                     select
                        distinct_id,
                        pointer_target_fixed,
                        round((x / viewport_width), 2) as pointer_relative_x,
                        y * scale_factor as client_y
                     from heatmaps
                     where {predicates}
                )
            group by `pointer_target_fixed`, pointer_relative_x, client_y
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
"""


class HeatmapsRequestSerializer(serializers.Serializer):
    viewport_width_min = serializers.IntegerField(required=False)
    viewport_width_max = serializers.IntegerField(required=False)
    type = serializers.CharField(required=False, default="click")
    date_from = serializers.CharField(required=False, default="-7d")
    date_to = serializers.CharField(required=False)
    url_exact = serializers.CharField(required=False)
    url_pattern = serializers.CharField(required=False)
    aggregation = serializers.ChoiceField(
        required=False,
        choices=["unique_visitors", "total_count"],
        help_text="How to aggregate the response",
        default="total_count",
    )
    filter_test_accounts = serializers.BooleanField(required=False, default=None, allow_null=True)

    def validate_date(self, value, label: Literal["date_from", "date_to"]) -> date:
        try:
            if isinstance(value, str):
                parsed_date, _, _ = relative_date_parse_with_delta_mapping(value, self.context["team"].timezone_info)
                return parsed_date.date()
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            else:
                raise serializers.ValidationError(f"Invalid {label} provided: {value}")
        except Exception:
            raise serializers.ValidationError(f"Error parsing provided {label}: {value}")

    def validate_date_from(self, value) -> date:
        return self.validate_date(value, "date_from")

    def validate_date_to(self, value) -> date:
        return self.validate_date(value, "date_to")

    def validate_url_pattern(self, value: str | None) -> str | None:
        if value is None:
            return None

        validated_value = value

        # we insist on the pattern being anchored
        if not value.startswith("^"):
            validated_value = f"^{value}"
        if not value.endswith("$"):
            validated_value = f"{validated_value}$"

        # KLUDGE: we allow API callers to send something that isn't really `re2` syntax used in match()
        # KLUDGE: so if it has * but not .* then we expect at least one character to match, so we use .+ instead
        # KLUDGE: this means we don't support valid regex since we can't support matching aaaaa with a*
        # KLUDGE: but you could send a+ and it would match aaaaa
        validated_value = "".join(
            [
                f".+" if c == "*" and i > 0 and validated_value[i - 1] != "." else c
                for i, c in enumerate(validated_value)
            ]
        )

        return validated_value

    def validate(self, values) -> dict:
        url_exact = values.get("url_exact", None)
        url_pattern = values.get("url_pattern", None)
        if isinstance(url_exact, str) and isinstance(url_pattern, str):
            if url_exact == url_pattern:
                values.pop("url_pattern")
            else:
                values.pop("url_exact")

        if values.get("filter_test_accounts") and not isinstance(values.get("filter_test_accounts"), bool):
            raise serializers.ValidationError("filter_test_accounts must be a boolean")

        return values


class HeatmapResponseItemSerializer(serializers.Serializer):
    count = serializers.IntegerField(required=True)
    pointer_y = serializers.IntegerField(required=True)
    pointer_relative_x = serializers.FloatField(required=True)
    pointer_target_fixed = serializers.BooleanField(required=True)


class HeatmapsResponseSerializer(serializers.Serializer):
    results = HeatmapResponseItemSerializer(many=True)


class HeatmapScrollDepthResponseItemSerializer(serializers.Serializer):
    cumulative_count = serializers.IntegerField(required=True)
    bucket_count = serializers.IntegerField(required=True)
    scroll_depth_bucket = serializers.IntegerField(required=True)


class HeatmapsScrollDepthResponseSerializer(serializers.Serializer):
    results = HeatmapScrollDepthResponseItemSerializer(many=True)


class HeatmapViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = HeatmapsResponseSerializer

    authentication_classes = [TemporaryTokenAuthentication]

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        request_serializer = HeatmapsRequestSerializer(data=request.query_params, context={"team": self.team})
        request_serializer.is_valid(raise_exception=True)

        aggregation = request_serializer.validated_data.pop("aggregation")
        placeholders: dict[str, Expr] = {k: Constant(value=v) for k, v in request_serializer.validated_data.items()}
        placeholders["date_to"] = placeholders.get("date_to", Constant(value=date.today().strftime("%Y-%m-%d")))
        is_scrolldepth_query = placeholders.get("type", None) == Constant(value="scrolldepth")

        raw_query = SCROLL_DEPTH_QUERY if is_scrolldepth_query else DEFAULT_QUERY

        aggregation_count = self._choose_aggregation(aggregation, is_scrolldepth_query)
        exprs = self._predicate_expressions(placeholders)

        if request_serializer.validated_data.get("filter_test_accounts") is True:
            date_from: date = request_serializer.validated_data["date_from"]
            date_to: date | None = request_serializer.validated_data.get("date_to", None)
            events_select = replace_filters(
                parse_select(
                    "SELECT distinct $session_id FROM events where notEmpty($session_id) AND {filters}", placeholders={}
                ),
                HogQLFilters(
                    filterTestAccounts=True,
                    dateRange=DateRange(
                        date_from=date_from.strftime("%Y-%m-%d"),
                        date_to=date_to.strftime("%Y-%m-%d") if date_to else (date.today()).strftime("%Y-%m-%d"),
                    ),
                ),
                self.team,
            )
            session_filter_expr = ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["session_id"]),
                right=events_select,
            )
            exprs.append(session_filter_expr)

        stmt = parse_select(raw_query, {"aggregation_count": aggregation_count, "predicates": ast.And(exprs=exprs)})
        context = HogQLContext(team_id=self.team.pk, limit_top_select=False)
        results = execute_hogql_query(query=stmt, team=self.team, limit_context=LimitContext.HEATMAPS, context=context)

        if is_scrolldepth_query:
            return self._return_scroll_depth_response(results)
        else:
            return self._return_heatmap_coordinates_response(results)

    def _choose_aggregation(self, aggregation, is_scrolldepth_query):
        aggregation_value = "count(*) as cnt" if aggregation == "total_count" else "count(distinct distinct_id) as cnt"
        if is_scrolldepth_query:
            aggregation_value = "count(*)" if aggregation == "total_count" else "count(distinct distinct_id)"
        aggregation_count = parse_expr(aggregation_value)
        return aggregation_count

    @staticmethod
    def _predicate_expressions(placeholders: dict[str, Expr]) -> List[ast.Expr]:  # noqa: UP006
        predicate_expressions: list[ast.Expr] = []

        predicate_mapping: dict[str, str] = {
            # should always have values
            "date_from": "timestamp >= {date_from}",
            "type": "`type` = {type}",
            # optional
            "date_to": "timestamp <= {date_to} + interval 1 day",
            "viewport_width_min": "viewport_width >= round({viewport_width_min} / 16)",
            "viewport_width_max": "viewport_width <= round({viewport_width_max} / 16)",
            "url_exact": "current_url = {url_exact}",
            "url_pattern": "match(current_url, {url_pattern})",
        }

        for predicate_key in placeholders.keys():
            # we e.g. don't want to add the filter_test_accounts predicate here
            if predicate_key in predicate_mapping:
                predicate_expressions.append(
                    parse_expr(predicate_mapping[predicate_key], {predicate_key: placeholders[predicate_key]})
                )

        if len(predicate_expressions) == 0:
            raise serializers.ValidationError("must always generate some filter conditions")

        return predicate_expressions

    @staticmethod
    def _return_heatmap_coordinates_response(query_response: HogQLQueryResponse) -> response.Response:
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

        resp = response.Response(response_serializer.data, status=status.HTTP_200_OK)
        resp["Cache-Control"] = "max-age=30"
        resp["Vary"] = "Accept, Accept-Encoding, Query-String"
        return resp

    @staticmethod
    def _return_scroll_depth_response(query_response: HogQLQueryResponse) -> response.Response:
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

        resp = response.Response(response_serializer.data, status=status.HTTP_200_OK)
        resp["Cache-Control"] = "max-age=30"
        resp["Vary"] = "Accept, Accept-Encoding, Query-String"
        return resp


class LegacyHeatmapViewSet(HeatmapViewSet):
    param_derived_from_user_current_team = "team_id"
