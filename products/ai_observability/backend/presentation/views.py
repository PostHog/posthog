import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pydantic
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from loginas.utils import is_impersonated_session
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.schema import (
    AnyPropertyFilterDiscriminated,
    CohortPropertyFilter,
    ElementPropertyFilter,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    GroupPropertyFilter,
    PersonPropertyFilter,
    SessionPropertyFilter,
)

from posthog.hogql.errors import QueryError

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models.user import User

from ..facade import api, contracts
from .query_concurrency import query_concurrency_slots
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


_PROPERTY_FILTERS_ADAPTER: pydantic.TypeAdapter[list[AnyPropertyFilterDiscriminated]] = pydantic.TypeAdapter(
    list[AnyPropertyFilterDiscriminated]
)


_LIST_PROPERTY_FILTERS = (
    EventPropertyFilter,
    EventMetadataPropertyFilter,
    PersonPropertyFilter,
    SessionPropertyFilter,
    GroupPropertyFilter,
    CohortPropertyFilter,
    ElementPropertyFilter,
)


class PropertyFiltersField(serializers.CharField):
    """A JSON-encoded list of property filters in a query string, validated into schema types."""

    def run_validation(self, data: Any = serializers.empty) -> list[AnyPropertyFilterDiscriminated]:
        raw = super().run_validation(data)
        if not raw:
            return []
        try:
            filters = _PROPERTY_FILTERS_ADAPTER.validate_python(json.loads(raw))
        except (json.JSONDecodeError, pydantic.ValidationError) as error:
            raise serializers.ValidationError(f"Properties are unparsable: {error}")
        # Other types, such as HogQL or data warehouse filters, let a caller reach any table HogQL can join, which
        # needs the query scope and not this resource's read scope.
        if any(not isinstance(property_filter, _LIST_PROPERTY_FILTERS) for property_filter in filters):
            raise serializers.ValidationError("Only the property filter types the traces list offers are supported.")
        return filters


class TraceNeighboursQuerySerializer(serializers.Serializer):
    created_at = serializers.DateTimeField(
        help_text="The trace's `createdAt` from the trace resource. With the trace id, it is the trace's position in the traces list."
    )
    date_from = serializers.CharField(
        required=False,
        help_text="Start of the traces list's date range, relative such as `-7d` or absolute. Neighbours stay within 3 days of the trace either way.",
    )
    date_to = serializers.CharField(
        required=False, help_text="End of the traces list's date range, relative or absolute."
    )
    properties = PropertyFiltersField(
        required=False,
        help_text="The traces list's property filters, JSON-encoded: event, event metadata, person, session, group, cohort or element filters. A trace is a neighbour when any of its events matches them.",
    )
    filter_test_accounts = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Whether to apply the project's test account filters. Defaults to the project's setting.",
    )

    def validate_created_at(self, value: datetime) -> datetime:
        if not api.is_usable_neighbour_anchor(value):
            raise serializers.ValidationError("Created at is out of range.")
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


class TraceViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "llm_analytics"
    scope_object_read_actions = ["retrieve", "node", "evaluations", "neighbours"]
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
        query_serializer=TraceNeighboursQuerySerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceNeighbours),
            400: OpenApiResponse(description="The encoded trace id or a query parameter is malformed or out of range."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_neighbours_retrieve",
    )
    @action(detail=True, methods=["GET"], url_path="neighbours")
    def neighbours(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """The traces just older and newer than this one in the traces list's order, under the list filters the request carries (search is not applied), within 3 days of it."""
        try:
            trace_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        query = request.validated_query_data
        filter_test_accounts = query.get("filter_test_accounts")
        try:
            neighbours = self._read(
                request,
                lambda user, _hint: api.get_trace_neighbours(
                    self.team,
                    user,
                    trace_id,
                    query["created_at"],
                    date_from=query.get("date_from"),
                    date_to=query.get("date_to"),
                    properties=query.get("properties") or [],
                    filter_test_accounts=(
                        bool(self.team.test_account_filters_default_checked)
                        if filter_test_accounts is None
                        else filter_test_accounts
                    ),
                    include_support_traces=is_impersonated_session(request),
                ),
            )
        except QueryError as error:
            # Filters the schema accepts can still be invalid, such as a regex that does not compile.
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(neighbours.model_dump(mode="json", by_alias=True))
