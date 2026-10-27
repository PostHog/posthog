from collections.abc import Callable
from datetime import datetime
from typing import Any

from django.http import HttpResponseBase

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.helpers.impersonation import is_impersonated
from posthog.models.user import User

from products.exports.backend.facade.api import get_export_asset, get_export_asset_content_response

from ..facade import api, contracts
from .query_concurrency import query_concurrency_slots
from .trace_exports import TraceExportRateThrottle
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment


class TraceQuerySerializer(serializers.Serializer):
    timestamp_hint = serializers.DateTimeField(
        required=False,
        help_text="When the trace happened, as carried by links into it. Lets a trace older than the AI events retention load from the shared events table.",
    )

    def validate_timestamp_hint(self, value: datetime) -> datetime:
        if not api.is_usable_timestamp_hint(value):
            raise serializers.ValidationError("Timestamp hint is out of range.")
        return value


TRACE_ID_PARAMETER = OpenApiParameter(
    "id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="The trace id, sent as the unpadded base64url encoding of its UTF-8 bytes.",
)
NODE_ID_PARAMETER = OpenApiParameter(
    "node_id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="The node id, sent as the unpadded base64url encoding of its UTF-8 bytes. The root node's id is the trace id.",
)
THROTTLED_RESPONSE = OpenApiResponse(description="Too many queries are running for the project or organization.")
EXPORT_ID_PARAMETER = OpenApiParameter(
    "export_id", OpenApiTypes.INT, OpenApiParameter.PATH, description="The export id the create call returned."
)
EXPORT_NOT_FOUND_RESPONSE = OpenApiResponse(description="You have no export with this id for this trace.")


# Gives the export request body its own schema, apart from the trace read's query parameters.
class TraceExportCreateSerializer(TraceQuerySerializer):
    pass


class TraceExportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the file cannot be downloaded yet.")


class TraceViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "llm_analytics"
    scope_object_read_actions = ["retrieve", "node", "evaluations", "exports", "export_status", "export_content"]
    # Traces are project-wide data, so a grant on a single llm_analytics object must not open them.
    requires_resource_level_access = True
    serializer_class = _FallbackSerializer

    def _read[T](self, request: ValidatedRequest, read: Callable[[User | None, datetime | None], T]) -> T:
        tag_queries(feature=Feature.QUERY)
        user = request.user if isinstance(request.user, User) else None
        with query_concurrency_slots(self.team):
            return read(user, request.validated_query_data.get("timestamp_hint"))

    @validated_request(
        query_serializer=TraceQuerySerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.Trace),
            400: OpenApiResponse(description="The timestamp hint or the encoded trace id is malformed."),
            404: OpenApiResponse(description="No trace with this id in the project."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_retrieve",
    )
    def retrieve(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """A trace ready to render: its tree with roll-ups, timeline, totals and person, without inputs or outputs."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            trace = self._read(request, lambda user, hint: api.get_trace(self.team, user, trace_id, hint))
        except api.TraceNotFoundError:
            return Response({"detail": "Trace not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(trace.model_dump(mode="json", by_alias=True))

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
    @action(detail=True, methods=["GET"], url_path=r"nodes/(?P<node_id>[A-Za-z0-9_-]+)")
    def node(self, request: ValidatedRequest, pk: str, node_id: str, **kwargs: Any) -> Response:
        """One node of a trace: its event properties as ingested, the keys that hold its input, output and tools, its error and its metadata."""
        try:
            trace_id = decode_trace_id_segment(pk)
            decoded_node_id = decode_trace_id_segment(node_id)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded id."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            node = self._read(
                request, lambda user, hint: api.get_trace_node(self.team, user, trace_id, decoded_node_id, hint)
            )
        except api.TraceNodeNotFoundError:
            return Response({"detail": "Node not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(node.model_dump(mode="json", by_alias=True))

    @validated_request(
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceEvaluationResults),
            400: OpenApiResponse(description="The encoded trace id is malformed."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_evaluations_retrieve",
    )
    @action(detail=True, methods=["GET"], url_path="evaluations")
    def evaluations(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """A trace's evaluation results, newest first and at most 250, each with its outcome and label ready to render."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        results = self._read(request, lambda user, _hint: api.get_trace_evaluation_results(self.team, user, trace_id))
        return Response(results.model_dump(mode="json", by_alias=True))

    @validated_request(
        request_serializer=TraceExportCreateSerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            201: OpenApiResponse(response=contracts.TraceExport),
            400: OpenApiResponse(description="The timestamp hint or the encoded trace id is malformed."),
            429: OpenApiResponse(description="Too many exports were requested."),
        },
        operation_id="ai_observability_traces_exports_create",
    )
    @action(detail=True, methods=["POST"], url_path="exports", throttle_classes=[TraceExportRateThrottle])
    def exports(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """Starts writing the trace and every node, inputs and outputs included, to a JSON file. Poll the export until it completes, then download it."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        export = api.create_trace_export(
            self.team,
            _user(request),
            trace_id,
            request.validated_data.get("timestamp_hint"),
            was_impersonated=is_impersonated(request),
        )
        return Response(export.model_dump(mode="json", by_alias=True), status=status.HTTP_201_CREATED)

    @validated_request(
        parameters=[TRACE_ID_PARAMETER, EXPORT_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceExport),
            400: OpenApiResponse(description="The encoded trace id is malformed."),
            404: EXPORT_NOT_FOUND_RESPONSE,
        },
        operation_id="ai_observability_traces_exports_retrieve",
    )
    @action(detail=True, methods=["GET"], url_path=r"exports/(?P<export_id>\d+)")
    def export_status(self, request: ValidatedRequest, pk: str, export_id: str, **kwargs: Any) -> Response:
        """The state of one of your exports of this trace."""
        try:
            export = self._trace_export(request, pk, export_id)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        except api.TraceExportNotFoundError:
            return Response({"detail": "Export not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(export.model_dump(mode="json", by_alias=True))

    @extend_schema(
        parameters=[TRACE_ID_PARAMETER, EXPORT_ID_PARAMETER],
        responses={
            (200, "application/json"): OpenApiResponse(response=contracts.TraceExportFile),
            400: OpenApiResponse(description="The encoded trace id is malformed."),
            404: EXPORT_NOT_FOUND_RESPONSE,
            409: OpenApiResponse(
                response=TraceExportErrorSerializer, description="The export is still being written, or failed."
            ),
        },
        operation_id="ai_observability_traces_exports_content_retrieve",
    )
    @action(detail=True, methods=["GET"], url_path=r"exports/(?P<export_id>\d+)/content")
    def export_content(self, request: Request, pk: str, export_id: str, **kwargs: Any) -> HttpResponseBase:
        """Downloads a completed export as a JSON file."""
        try:
            export = self._trace_export(request, pk, export_id)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        except api.TraceExportNotFoundError:
            return Response({"detail": "Export not found."}, status=status.HTTP_404_NOT_FOUND)
        asset = get_export_asset(team_id=self.team.pk, asset_id=export.id)
        if export.status != "complete" or asset is None:
            detail = export.exception or "The export is still being prepared."
            return Response({"detail": detail}, status=status.HTTP_409_CONFLICT)
        return get_export_asset_content_response(asset=asset, download=True)

    def _trace_export(self, request: Request, pk: str, export_id: str) -> contracts.TraceExport:
        return api.get_trace_export(self.team, _user(request), decode_trace_id_segment(pk), int(export_id))


def _user(request: Request) -> User:
    # An export runs later as the user who asked for it, so unlike a trace read it cannot go without one.
    if not isinstance(request.user, User):
        raise NotAuthenticated()
    return request.user
