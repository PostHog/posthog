from datetime import date, datetime
from typing import Any, List, Literal  # noqa: UP035

from django.http import HttpResponse

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
from posthog.api.utils import action
from posthog.auth import TemporaryTokenAuthentication
from posthog.models.heatmap_screenshot import HeatmapScreenshot
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.tasks.heatmap_screenshot import generate_heatmap_screenshot
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


# Heatmap Screenshot functionality
class HeatmapScreenshotRequestSerializer(serializers.Serializer):
    url = serializers.URLField(required=True, max_length=2000)
    width = serializers.IntegerField(required=False, default=1400, min_value=100, max_value=3000)
    force_reload = serializers.BooleanField(required=False, default=False)


class HeatmapScreenshotResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = HeatmapScreenshot
        fields = [
            "id",
            "url",
            "data_url",
            "width",
            "type",
            "status",
            "has_content",
            "created_at",
            "updated_at",
            "exception",
        ]
        read_only_fields = [
            "id",
            "status",
            "has_content",
            "created_at",
            "updated_at",
            "exception",
        ]


class HeatmapScreenshotViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = HeatmapScreenshotResponseSerializer
    authentication_classes = [TemporaryTokenAuthentication]
    queryset = HeatmapScreenshot.objects.all()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team)

    @action(methods=["POST"], detail=False)
    def generate(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        request_serializer = HeatmapScreenshotRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        url = request_serializer.validated_data["url"]
        width = request_serializer.validated_data["width"]
        force_reload = request_serializer.validated_data["force_reload"]

        # Check if screenshot already exists
        existing_screenshot = None
        try:
            existing_screenshot = HeatmapScreenshot.objects.get(team=self.team, url=url, width=width)
        except HeatmapScreenshot.DoesNotExist:
            pass

        # Handle existing screenshot based on force_reload and status
        if existing_screenshot and not force_reload:
            if existing_screenshot.status == HeatmapScreenshot.Status.COMPLETED and existing_screenshot.has_content:
                # Return existing completed screenshot
                response_serializer = HeatmapScreenshotResponseSerializer(existing_screenshot)
                return response.Response(response_serializer.data, status=status.HTTP_200_OK)
            elif existing_screenshot.status == HeatmapScreenshot.Status.PROCESSING:
                # Return processing screenshot
                response_serializer = HeatmapScreenshotResponseSerializer(existing_screenshot)
                return response.Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)

        # Create new screenshot or update existing one for force_reload
        if existing_screenshot and force_reload:
            existing_screenshot.status = HeatmapScreenshot.Status.PROCESSING
            existing_screenshot.content = None
            existing_screenshot.content_location = None
            existing_screenshot.exception = None
            existing_screenshot.created_by = request.user
            existing_screenshot.save()
            screenshot = existing_screenshot
        elif not existing_screenshot:
            screenshot = HeatmapScreenshot.objects.create(
                team=self.team,
                url=url,
                width=width,
                created_by=request.user,
                status=HeatmapScreenshot.Status.PROCESSING,
            )
        else:
            # This should not happen as we already handled existing screenshots above
            screenshot = existing_screenshot

        generate_heatmap_screenshot.delay(screenshot.id)

        response_serializer = HeatmapScreenshotResponseSerializer(screenshot)
        return response.Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)

    @action(methods=["GET"], detail=True)
    def content(self, request: request.Request, *args: Any, **kwargs: Any) -> HttpResponse:
        screenshot = self.get_object()

        if not screenshot.has_content:
            # Return JSON response with screenshot status instead of plain text error
            response_serializer = HeatmapScreenshotResponseSerializer(screenshot)
            return response.Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)

        if screenshot.content:
            http_response = HttpResponse(screenshot.content, content_type="image/jpeg")
            http_response["Content-Disposition"] = f'attachment; filename="screenshot-{screenshot.id}.jpg"'
            return http_response
        elif screenshot.content_location:
            # Handle object storage case (similar to ExportedAsset)
            # For now, just return not implemented
            response_serializer = HeatmapScreenshotResponseSerializer(screenshot)
            return response.Response(
                {**response_serializer.data, "error": "Content location not implemented yet"},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )
        else:
            response_serializer = HeatmapScreenshotResponseSerializer(screenshot)
            return response.Response(
                {**response_serializer.data, "error": "No content available"}, status=status.HTTP_404_NOT_FOUND
            )


class HeatmapSavedRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = HeatmapScreenshot
        fields = ["url", "data_url", "width", "type"]
        extra_kwargs = {
            "url": {"required": True},
            "data_url": {"required": False, "allow_null": True},
            "width": {"required": False, "default": 1400},
            "type": {"required": False, "default": HeatmapScreenshot.Type.SCREENSHOT},
        }


class HeatmapSavedViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = HeatmapScreenshotResponseSerializer
    authentication_classes = [TemporaryTokenAuthentication]
    queryset = HeatmapScreenshot.objects.all()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        qs = self.safely_get_queryset(self.get_queryset()).order_by("-updated_at")

        type_param = request.query_params.get("type")
        status_param = request.query_params.get("status")
        search = request.query_params.get("search")

        if type_param:
            qs = qs.filter(type=type_param)
        if status_param:
            qs = qs.filter(status=status_param)
        if search:
            qs = qs.filter(url__icontains=search)

        limit = int(request.query_params.get("limit", 100))
        offset = int(request.query_params.get("offset", 0))
        count = qs.count()
        results = qs[offset : offset + limit]

        data = HeatmapScreenshotResponseSerializer(results, many=True).data
        return response.Response({"results": data, "count": count}, status=status.HTTP_200_OK)

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        serializer = HeatmapSavedRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        url = serializer.validated_data["url"]
        data_url = serializer.validated_data.get("data_url") or url
        width = serializer.validated_data.get("width", 1400)
        heatmap_type = serializer.validated_data.get("type", HeatmapScreenshot.Type.SCREENSHOT)

        screenshot = HeatmapScreenshot.objects.create(
            team=self.team,
            url=url,
            data_url=data_url,
            width=width,
            type=heatmap_type,
            created_by=request.user,
            status=HeatmapScreenshot.Status.PROCESSING
            if heatmap_type == HeatmapScreenshot.Type.SCREENSHOT
            else HeatmapScreenshot.Status.COMPLETED,
        )

        if heatmap_type == HeatmapScreenshot.Type.SCREENSHOT:
            generate_heatmap_screenshot.delay(screenshot.id)

        return response.Response(HeatmapScreenshotResponseSerializer(screenshot).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        obj = self.get_object()
        return response.Response(HeatmapScreenshotResponseSerializer(obj).data, status=status.HTTP_200_OK)

    def partial_update(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        obj = self.get_object()
        serializer = HeatmapSavedRequestSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return response.Response(HeatmapScreenshotResponseSerializer(updated).data, status=status.HTTP_200_OK)

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        obj = self.get_object()
        obj.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["POST"], detail=True)
    def regenerate(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        obj = self.get_object()
        if obj.type != HeatmapScreenshot.Type.SCREENSHOT:
            return response.Response(
                {"detail": "Regenerate only supported for screenshot type"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        obj.status = HeatmapScreenshot.Status.PROCESSING
        obj.content = None
        obj.content_location = None
        obj.exception = None
        obj.save()
        generate_heatmap_screenshot.delay(obj.id)
        return response.Response(HeatmapScreenshotResponseSerializer(obj).data, status=status.HTTP_202_ACCEPTED)
