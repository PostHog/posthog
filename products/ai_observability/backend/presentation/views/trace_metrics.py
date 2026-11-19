from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.helpers.impersonation import is_impersonated

from ...facade import api, contracts
from .trace_resource import THROTTLED_RESPONSE, TraceResourceViewSet, request_user
from .traces import TraceListQuerySerializer

RANGE_TOO_LONG_DETAIL = "This range is too long to compute. Try a shorter one."
_LIST_FIELDS = TraceListQuerySerializer().fields


class TraceMetricsQuerySerializer(serializers.Serializer):
    date_from = _LIST_FIELDS["date_from"]
    date_to = _LIST_FIELDS["date_to"]
    filter_test_accounts = _LIST_FIELDS["filter_test_accounts"]


class TraceMetricsViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["list"]

    @validated_request(
        query_serializer=TraceMetricsQuerySerializer,
        responses={
            200: OpenApiResponse(response=contracts.TraceMetrics),
            400: OpenApiResponse(description="The date range is invalid."),
            422: OpenApiResponse(description="The date range is too long to compute. Try a shorter one."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_metrics_list",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Six metrics for the project's traces in a date range, each compared with the period right before it, and
        the same metrics for each hour or day of the range."""
        query = request.validated_query_data
        user = request_user(request)
        try:
            selection = api.TraceSelection(
                window=api.resolve_trace_window(self.team, query.get("date_from"), query.get("date_to")),
                filter_test_accounts=query["filter_test_accounts"],
                include_support_traces=is_impersonated(request),
            )
            build = self._read(request, lambda _user, _hint: api.load_trace_metrics(self.team, user, selection))
        except api.InvalidTraceWindowError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        except api.TraceMetricsTooHeavyError:
            return Response(
                {"detail": RANGE_TOO_LONG_DETAIL, "code": "range_too_long"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return Response(build().model_dump(mode="json", by_alias=True))
