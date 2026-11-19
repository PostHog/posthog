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
    page_limit_field,
    require_query_scope_for_filters,
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


SESSION_SCOPE_FILTERS_MESSAGE = "A session reads on its own. Remove the list filters."
SESSION_SCOPE_EXCLUDED_PARAMS = (
    "properties",
    "search",
    "view",
    "person_id",
    "group_key",
    "group_type_index",
    "filter_test_accounts",
)


class TraceListQuerySerializer(ListFilterQuerySerializer):
    view = serializers.ChoiceField(
        choices=api.QUICK_FILTERS,
        required=False,
        help_text="Lists only traces with an error, or only traces with user feedback. The counts ignore it.",
    )
    session_id = serializers.CharField(
        required=False,
        max_length=400,
        help_text="Lists only the traces of the session with this id. A session reads on its own, so it can't be sent "
        "with the properties, search, view, person, group or test account parameters.",
    )
    order = serializers.ChoiceField(
        choices=api.TRACE_ORDERS,
        default="newest_first",
        help_text="Which trace comes first: the newest or the oldest. Defaults to the newest.",
    )
    before_cursor = serializers.CharField(
        required=False,
        help_text="The previousCursor of a page, to read the page before it. Send only one of cursor, beforeCursor "
        "and around.",
    )
    around = serializers.CharField(
        required=False,
        help_text="A trace id, to read the page that holds that trace with the traces before it. Send only one of "
        "cursor, beforeCursor and around.",
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
        """The project's traces in a date range, or one session's traces, in either order, a page at a time and in
        either direction. The first page of a project's list also carries how many traces the selection holds."""
        query = request.validated_query_data
        if "session_id" in query and any(name in request.query_params for name in SESSION_SCOPE_EXCLUDED_PARAMS):
            return Response({"detail": SESSION_SCOPE_FILTERS_MESSAGE}, status=status.HTTP_400_BAD_REQUEST)
        require_query_scope_for_filters(request, query)
        user = request_user(request)
        try:
            selection = self._selection(request)
            build = self._read(
                request,
                lambda _user, _hint: api.load_trace_list(
                    self.team,
                    user,
                    selection,
                    cursor=query.get("cursor"),
                    before_cursor=query.get("before_cursor"),
                    around=query.get("around"),
                    limit=query["limit"],
                ),
            )
        except (
            api.InvalidTraceWindowError,
            api.InvalidTraceCursorError,
            api.InvalidTraceSelectionError,
            api.TraceNotInSelectionError,
            ExposedHogQLError,
            ExposedCHQueryError,
        ) as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        # Built after the query slot is released, so building a page of traces never holds the team's slot.
        return Response(build().model_dump(mode="json", by_alias=True))

    def _selection(self, request: ValidatedRequest) -> api.TraceSelection:
        query = request.validated_query_data
        window = api.resolve_trace_window(self.team, query.get("date_from"), query.get("date_to"))
        if "session_id" in query:
            return api.TraceSelection(
                window=window,
                include_support_traces=is_impersonated(request),
                session_id=query["session_id"],
                order=query["order"],
            )
        return api.TraceSelection(
            window=window,
            order=query["order"],
            include_support_traces=is_impersonated(request),
            quick_filter=query.get("view"),
            **selection_filters(query),
        )
