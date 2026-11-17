from collections.abc import Callable
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.models import Team, User

from ...facade import api, contracts
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment
from .trace_resource import THROTTLED_RESPONSE, TRACE_ID_PARAMETER, TraceQuerySerializer, TraceResourceViewSet

NODE_ID_PARAMETER = OpenApiParameter(
    "node_id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="The node id, sent as the unpadded base64url encoding of its UTF-8 bytes. The root node's id is the trace id.",
)


class TraceNodeDatasetItemQuerySerializer(TraceQuerySerializer):
    timestamp_hint = serializers.DateTimeField(
        help_text="When the trace happened, as carried by links into it. Saved as the dataset item's source timestamp, and lets a trace older than the AI events retention load from the shared events table.",
    )


class TraceNodeParserTestRequestSerializer(serializers.Serializer):
    source = serializers.CharField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        # Preserve the YAML verbatim
        trim_whitespace=False,
        max_length=contracts.PARSER_RECIPE_MAX_SOURCE_LENGTH,
        help_text="The parser recipe to test, as raw YAML in the custom parser DSL.",
    )


class TraceNodeViewSet(TraceResourceViewSet):
    # Testing a parser saves nothing, so it is a read even though it posts the parser.
    scope_object_read_actions = ["retrieve", "raw", "dataset_item", "parser_test"]
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

    @validated_request(
        query_serializer=TraceNodeDatasetItemQuerySerializer,
        parameters=[TRACE_ID_PARAMETER, NODE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceNodeDatasetItem),
            400: OpenApiResponse(
                description="The timestamp hint is missing or malformed, or an encoded id is malformed."
            ),
            404: OpenApiResponse(description="No node with this id in the trace."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_nodes_dataset_item_retrieve",
    )
    @action(detail=True, methods=["GET"])
    def dataset_item(self, request: ValidatedRequest, node_id: str, **kwargs: Any) -> Response:
        """One node of a trace as a dataset item: its input and output as ingested, and its custom properties as metadata. The root node gives the trace's input and output state with no metadata."""
        return self._node_response(request, node_id, api.load_trace_node_dataset_item)

    @validated_request(
        request_serializer=TraceNodeParserTestRequestSerializer,
        query_serializer=TraceQuerySerializer,
        parameters=[TRACE_ID_PARAMETER, NODE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceNodeParserTest),
            400: OpenApiResponse(
                description="The parser does not compile, with the reason in `detail`, or the timestamp hint or an "
                "encoded id is malformed."
            ),
            404: OpenApiResponse(description="No node with this id in the trace."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_nodes_parser_test_create",
    )
    @action(detail=True, methods=["POST"])
    def parser_test(self, request: ValidatedRequest, node_id: str, **kwargs: Any) -> Response:
        """Tests a custom parser recipe against one node without saving it: the node's input and output as they would render with the parser saved, and whether it parses every side that the project's saved parsers leave unparsed."""
        source = request.validated_data["source"]
        try:
            return self._node_response(
                request,
                node_id,
                lambda team, user, trace_id, decoded_node_id, hint: api.run_trace_node_parser_test(
                    team, user, trace_id, decoded_node_id, hint, source
                ),
            )
        except api.RecipeCompileError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    def _node_response(
        self,
        request: ValidatedRequest,
        node_id: str,
        load: Callable[[Team, User | None, str, str, Any], Callable[[], contracts.Contract]],
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
