from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import diagnostics
from ...facade.diagnostics_contracts import ErrorFirstSeenList
from .diagnostics_resource import DiagnosticsViewSet
from .errors import RANGE_TOO_LONG_RESPONSE
from .list_filters import TraceDateRangeQuerySerializer
from .trace_resource import THROTTLED_RESPONSE


class ErrorFirstSeenRequestSerializer(serializers.Serializer):
    keys = serializers.ListField(
        child=serializers.CharField(trim_whitespace=False),
        min_length=1,
        max_length=diagnostics.ERROR_FIRST_SEEN_MAX_KEYS,
        help_text=f"Up to {diagnostics.ERROR_FIRST_SEEN_MAX_KEYS} error keys, as the errors list hands them out.",
    )


class ErrorFirstSeenViewSet(DiagnosticsViewSet):
    scope_object_read_actions = ["create"]

    @validated_request(
        query_serializer=TraceDateRangeQuerySerializer,
        request_serializer=ErrorFirstSeenRequestSerializer,
        responses={
            200: OpenApiResponse(response=ErrorFirstSeenList),
            400: OpenApiResponse(description="A key, a parameter or the date range is invalid."),
            403: OpenApiResponse(description="The key lacks a required scope."),
            422: RANGE_TOO_LONG_RESPONSE,
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_errors_first_seen_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """A read that writes nothing: when each error first occurred, checked from 30 days before the date range to
        its end. It takes the keys in the body because a page of them does not fit in a query string. Send the date
        range and the test account switch of the list the keys came from. The check ignores the list's other
        filters."""
        selection = self._selection(request)
        first_seen = self._read(
            request,
            lambda user: diagnostics.load_error_first_seen(self.team, user, selection, request.validated_data["keys"]),
        )
        return Response(first_seen.model_dump(mode="json", by_alias=True))
