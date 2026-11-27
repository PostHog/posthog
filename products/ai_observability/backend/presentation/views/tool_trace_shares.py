from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import diagnostics
from ...facade.diagnostics_contracts import ToolTraceShareList
from .diagnostics_resource import RANGE_TOO_LONG_RESPONSE, SCOPE_RESPONSE, DiagnosticsViewSet
from .tools import ToolSelectionQuerySerializer
from .trace_resource import THROTTLED_RESPONSE


class ToolTraceSharesRequestSerializer(serializers.Serializer):
    keys = serializers.ListField(
        child=serializers.CharField(trim_whitespace=False),
        min_length=1,
        max_length=diagnostics.TOOL_TRACE_SHARES_MAX_KEYS,
        help_text=f"Up to {diagnostics.TOOL_TRACE_SHARES_MAX_KEYS} tool keys, as the tools list hands them out.",
    )


class ToolTraceSharesViewSet(DiagnosticsViewSet):
    scope_object_read_actions = ["create"]

    @validated_request(
        query_serializer=ToolSelectionQuerySerializer,
        request_serializer=ToolTraceSharesRequestSerializer,
        responses={
            200: OpenApiResponse(response=ToolTraceShareList),
            400: OpenApiResponse(description="A key, a parameter, the date range or a property filter is invalid."),
            403: SCOPE_RESPONSE,
            422: RANGE_TOO_LONG_RESPONSE,
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_tools_trace_shares_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """A read that writes nothing: the share of the date range's traces that called each tool. It takes the keys
        in the body because a page of them does not fit in a query string. Send the filters of the list the keys came
        from."""
        selection = self._selection(request)
        shares = self._read(
            request,
            lambda user: diagnostics.load_tool_trace_shares(self.team, user, selection, request.validated_data["keys"]),
        )
        return Response(shares.model_dump(mode="json", by_alias=True))
