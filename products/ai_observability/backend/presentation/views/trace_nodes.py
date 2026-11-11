from collections.abc import Callable
from datetime import datetime
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.models.team import Team
from posthog.models.user import User

from ...facade import api, contracts
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment
from .trace_resource import THROTTLED_RESPONSE, TRACE_ID_PARAMETER, TraceQuerySerializer, TraceResourceViewSet

NODE_ID_PARAMETER = OpenApiParameter(
    "node_id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="The node id, sent as the unpadded base64url encoding of its UTF-8 bytes. The root node's id is the trace id.",
)


class TraceNodeViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["retrieve", "raw"]
    lookup_url_kwarg = "node_id"
    lookup_value_regex = "[A-Za-z0-9_-]+"

    @validated_request(
        query_serializer=TraceQuerySerializer,
        parameters=[TRACE_ID_PARAMETER, NODE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceNodeDetail),
            400: OpenApiResponse(description="The timestamp hint or an encoded id is malformed."),
            404: OpenApiResponse(description="No node with this id in the trace."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_nodes_retrieve",
    )
    def retrieve(self, request: ValidatedRequest, node_id: str, **kwargs: Any) -> Response:
        """One node of a trace: its input and output ready to render, its event name, uuid and timestamp, its error and its metadata. The raw event properties are on the `raw` read."""
        return self._node_response(request, node_id, api.load_trace_node_detail)

    @validated_request(
        query_serializer=TraceQuerySerializer,
        parameters=[TRACE_ID_PARAMETER, NODE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceNodeRaw),
            400: OpenApiResponse(description="The timestamp hint or an encoded id is malformed."),
            404: OpenApiResponse(description="No node with this id in the trace."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_nodes_raw_retrieve",
    )
    @action(detail=True, methods=["GET"])
    def raw(self, request: ValidatedRequest, node_id: str, **kwargs: Any) -> Response:
        """One node of a trace as ingested: its event properties and the keys that hold its input, output and tools, with nothing normalized."""
        return self._node_response(request, node_id, api.load_trace_node_raw)

    def _node_response(
        self,
        request: ValidatedRequest,
        node_id: str,
        load: Callable[[Team, User | None, str, str, datetime | None], Callable[[], contracts.Contract]],
    ) -> Response:
        try:
            trace_id = decode_trace_id_segment(self.trace_segment)
            decoded_node_id = decode_trace_id_segment(node_id)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded id."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            build = self._read(request, lambda user, hint: load(self.team, user, trace_id, decoded_node_id, hint))
        except api.TraceNodeNotFoundError:
            return Response({"detail": "Node not found."}, status=status.HTTP_404_NOT_FOUND)
        # Only the ClickHouse load holds the query slot. Building the node normalizes its content, which runs no ClickHouse
        # query, so other reads of the organization do not wait on that work.
        return Response(build().model_dump(mode="json", by_alias=True))
