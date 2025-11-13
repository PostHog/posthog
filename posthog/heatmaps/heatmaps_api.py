from datetime import date, datetime
from typing import Any, List, Literal, cast  # noqa: UP035

from django.core.exceptions import FieldError
from django.db.models import Q
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

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.auth import TemporaryTokenAuthentication
from posthog.heatmaps.heatmaps_utils import DEFAULT_TARGET_WIDTHS, is_url_allowed
from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.heatmap_saved import SavedHeatmap
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AISustainedRateThrottle,
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
)
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


class HeatmapScreenshotResponseSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    snapshots = serializers.SerializerMethodField()

    class Meta:
        model = SavedHeatmap
        fields = [
            "id",
            "short_id",
            "name",
            "url",
            "data_url",
            "target_widths",
            "type",
            "status",
            "has_content",
            "snapshots",
            "deleted",
            "created_by",
            "created_at",
            "updated_at",
            "exception",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "status",
            "has_content",
            "created_by",
            "created_at",
            "updated_at",
            "exception",
        ]

    def get_snapshots(self, obj: SavedHeatmap) -> list[dict]:
        # Expose metadata of generated snapshots (width + readiness)
        snaps = []
        for snap in obj.snapshots.all():
            snaps.append(
                {
                    "width": snap.width,
                    "has_content": bool(snap.content or snap.content_location),
                }
            )
        snaps.sort(key=lambda s: s["width"])
        return snaps


class HeatmapScreenshotViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = HeatmapScreenshotResponseSerializer
    authentication_classes = [TemporaryTokenAuthentication]
    queryset = SavedHeatmap.objects.all()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team)

    @action(methods=["GET"], detail=True)
    def content(self, request: request.Request, *args: Any, **kwargs: Any) -> HttpResponse:
        screenshot = self.get_object()
        if screenshot.deleted:
            return response.Response(status=status.HTTP_404_NOT_FOUND)

        # Pick requested width or default
        try:
            requested_width = int(request.query_params.get("width", 1024))
        except (ValueError, TypeError):
            return response.Response(
                {"error": "Invalid width parameter, must be an integer"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Try exact match snapshot
        snapshot = screenshot.snapshots.filter(width=requested_width).first()

        # If not found, pick closest by absolute difference among available snapshots
        if not snapshot:
            all_snaps = list(screenshot.snapshots.all())
            if all_snaps:
                snapshot = min(all_snaps, key=lambda s: abs(s.width - requested_width))

        if not snapshot:
            # Nothing generated yet
            response_serializer = HeatmapScreenshotResponseSerializer(screenshot)
            return response.Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)

        if snapshot.content:
            http_response = HttpResponse(snapshot.content, content_type="image/jpeg")
            http_response["Content-Disposition"] = (
                f'attachment; filename="screenshot-{screenshot.id}-{snapshot.width}.jpg"'
            )
            return http_response
        elif snapshot.content_location:
            response_serializer = HeatmapScreenshotResponseSerializer(screenshot)
            return response.Response(
                {**response_serializer.data, "error": "Content location not implemented yet"},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )
        else:
            response_serializer = HeatmapScreenshotResponseSerializer(screenshot)
            return response.Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)


class SavedHeatmapRequestSerializer(serializers.ModelSerializer):
    widths = serializers.ListField(
        child=serializers.IntegerField(min_value=100, max_value=3000), required=False, allow_empty=False
    )

    def validate_url(self, value: str) -> str:
        ok, err = is_url_allowed(value)
        if not ok:
            raise serializers.ValidationError(err or "URL not allowed")
        return value

    class Meta:
        model = SavedHeatmap
        fields = ["name", "url", "data_url", "widths", "type", "deleted"]
        extra_kwargs = {
            "name": {"required": False, "allow_null": True},
            "url": {"required": True},
            "data_url": {"required": False, "allow_null": True},
            "type": {"required": False, "default": SavedHeatmap.Type.SCREENSHOT},
            "deleted": {"required": False},
        }


class SavedHeatmapViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = HeatmapScreenshotResponseSerializer
    authentication_classes = [TemporaryTokenAuthentication]
    queryset = SavedHeatmap.objects.all()
    lookup_field = "short_id"

    def get_throttles(self):
        if self.action == "create":
            # More restrictive rate limiting for expensive screenshot generation
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        return super().get_throttles()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        qs = (
            self.safely_get_queryset(self.get_queryset())
            .filter(deleted=False)
            .select_related("created_by")
            .order_by("-updated_at")
        )

        type_param = request.query_params.get("type")
        status_param = request.query_params.get("status")
        search = request.query_params.get("search")
        created_by_param = request.query_params.get("created_by")
        order = request.query_params.get("order")

        if type_param:
            qs = qs.filter(type=type_param)
        if status_param:
            qs = qs.filter(status=status_param)
        if search:
            qs = qs.filter(Q(url__icontains=search) | Q(name__icontains=search))
        if created_by_param:
            try:
                qs = qs.filter(created_by_id=int(created_by_param))
            except (ValueError, TypeError):
                return response.Response(
                    {"error": "Invalid created_by parameter, must be an integer"}, status=status.HTTP_400_BAD_REQUEST
                )
        if order:
            try:
                qs = qs.order_by(order)
            except FieldError:
                return response.Response({"error": f"Invalid order field: {order}"}, status=status.HTTP_400_BAD_REQUEST)

        limit = int(request.query_params.get("limit", 100))
        offset = int(request.query_params.get("offset", 0))
        count = qs.count()
        results = qs[offset : offset + limit]

        data = HeatmapScreenshotResponseSerializer(results, many=True).data
        return response.Response({"results": data, "count": count}, status=status.HTTP_200_OK)

    def create(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        serializer = SavedHeatmapRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        name = serializer.validated_data.get("name")
        url = serializer.validated_data["url"]
        data_url = serializer.validated_data.get("data_url") or url
        widths = serializer.validated_data.get("widths", DEFAULT_TARGET_WIDTHS)
        heatmap_type = serializer.validated_data.get("type", SavedHeatmap.Type.SCREENSHOT)

        screenshot = SavedHeatmap.objects.create(
            team=self.team,
            name=name,
            url=url,
            data_url=data_url,
            target_widths=widths,
            type=heatmap_type,
            created_by=cast(User, request.user),
            status=SavedHeatmap.Status.PROCESSING
            if heatmap_type == SavedHeatmap.Type.SCREENSHOT
            else SavedHeatmap.Status.COMPLETED,
        )

        log_activity(
            organization_id=cast(User, request.user).current_organization_id
            if hasattr(request.user, "current_organization_id")
            else None,
            team_id=self.team.id,
            user=cast(User, request.user),
            item_id=screenshot.short_id or str(screenshot.id),
            scope="Heatmap",
            activity="created",
            detail=Detail(name=screenshot.name or screenshot.url, short_id=screenshot.short_id, type=screenshot.type),
            was_impersonated=getattr(request, "was_impersonated", False),
        )

        if heatmap_type == SavedHeatmap.Type.SCREENSHOT:
            generate_heatmap_screenshot.delay(screenshot.id)

        return response.Response(HeatmapScreenshotResponseSerializer(screenshot).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        obj = self.get_object()
        return response.Response(HeatmapScreenshotResponseSerializer(obj).data, status=status.HTTP_200_OK)

    def partial_update(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        obj = self.get_object()
        serializer = SavedHeatmapRequestSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        log_activity(
            organization_id=cast(User, request.user).current_organization_id
            if hasattr(request.user, "current_organization_id")
            else None,
            team_id=self.team.id,
            user=cast(User, request.user),
            item_id=updated.short_id or str(updated.id),
            scope="Heatmap",
            activity="updated",
            detail=Detail(name=updated.name or updated.url, short_id=updated.short_id, type=updated.type),
            was_impersonated=getattr(request, "was_impersonated", False),
        )
        return response.Response(HeatmapScreenshotResponseSerializer(updated).data, status=status.HTTP_200_OK)
