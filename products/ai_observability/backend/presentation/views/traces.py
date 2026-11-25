from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.errors import ExposedCHQueryError
from posthog.helpers.impersonation import is_impersonated

from ...facade import api, contracts
from .list_filters import (
    ListFilterQuerySerializer,
    group_scope_field,
    page_limit_field,
    person_scope_field,
    property_filters_field,
    require_query_scope_for_filters,
    search_field,
    selection_filters,
)
from .property_filters import QUERY_SCOPE
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment
from .trace_resource import (
    THROTTLED_RESPONSE,
    TRACE_ID_PARAMETER,
    TraceQuerySerializer,
    TraceResourceViewSet,
    request_user,
)


class TraceAvailabilityRequestSerializer(serializers.Serializer):
    trace_ids = serializers.ListField(
        child=serializers.CharField(max_length=255, trim_whitespace=False),
        min_length=1,
        max_length=2,
        help_text="Application and evaluator trace IDs to check without loading trace contents.",
    )


class TraceAvailabilitySerializer(serializers.Serializer):
    available_trace_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="Requested trace IDs readable from AI events or the shared events table.",
    )


class TraceListQuerySerializer(ListFilterQuerySerializer):
    properties = property_filters_field("A trace is listed when one of its events matches every filter.")
    search = search_field("the trace's generations and embeddings")
    person_id = person_scope_field("traces whose events")
    group_key = group_scope_field("traces whose events")
    view = serializers.ChoiceField(
        choices=api.QUICK_FILTERS,
        required=False,
        help_text="Lists only traces with an error, or only traces with user feedback. The counts ignore it.",
    )
    limit = page_limit_field("traces", default=api.TRACE_LIST_DEFAULT_LIMIT, maximum=api.TRACE_LIST_MAX_LIMIT)


class TraceViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["list", "retrieve", "availability"]

    @validated_request(
        request_serializer=TraceAvailabilityRequestSerializer,
        responses={200: TraceAvailabilitySerializer, 429: THROTTLED_RESPONSE},
        operation_id="ai_observability_traces_availability_create",
    )
    @action(detail=False, methods=["POST"])
    def availability(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        trace_ids = self._read(
            request,
            lambda user, _hint: api.get_available_trace_ids(self.team, user, request.validated_data["trace_ids"]),
        )
        return Response(TraceAvailabilitySerializer(instance={"available_trace_ids": trace_ids}).data)

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
        query_serializer=TraceListQuerySerializer,
        responses={
            200: OpenApiResponse(response=contracts.TraceList),
            400: OpenApiResponse(
                description="A parameter, the cursor, the date range or a property filter is invalid."
            ),
            403: OpenApiResponse(
                description=f"The key lacks a required scope, or a property filter needs the {QUERY_SCOPE} scope."
            ),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_list",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The project's traces in a date range, newest first, a page at a time. The first page also carries how many
        traces the selection holds."""
        query = request.validated_query_data
        require_query_scope_for_filters(request, query)
        user = request_user(request)
        try:
            selection = self._selection(request)
            build = self._read(
                request,
                lambda _user, _hint: api.load_trace_list(
                    self.team, user, selection, cursor=query.get("cursor"), limit=query["limit"]
                ),
            )
        except (
            api.InvalidTraceWindowError,
            api.InvalidTraceCursorError,
            api.InvalidTraceSelectionError,
            ExposedHogQLError,
            ExposedCHQueryError,
        ) as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        # Built after the query slot is released, so building a page of traces never holds the team's slot.
        return Response(build().model_dump(mode="json", by_alias=True))

    def _selection(self, request: ValidatedRequest) -> api.TraceSelection:
        query = request.validated_query_data
        return api.TraceSelection(
            window=api.resolve_trace_window(self.team, query.get("date_from"), query.get("date_to")),
            include_support_traces=is_impersonated(request),
            quick_filter=query.get("view"),
            **selection_filters(query),
        )
