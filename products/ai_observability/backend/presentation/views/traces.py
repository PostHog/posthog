from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.constants import GROUP_TYPES_LIMIT
from posthog.errors import ExposedCHQueryError
from posthog.helpers.impersonation import is_impersonated
from posthog.permissions import scopes_caller_lacks

from ...facade import api, contracts
from .property_filters import QUERY_SCOPE, QUERY_SCOPE_REQUIRED, PropertyFiltersField, filters_need_query_scope
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


class TraceListQuerySerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False,
        help_text="Start of the date range, as an ISO 8601 date or datetime, a relative date such as -24h or -7d, "
        "or all for the past year. Defaults to seven days ago.",
    )
    date_to = serializers.CharField(
        required=False,
        help_text="End of the date range, as an ISO 8601 date or datetime or a relative date. A date without a time "
        "includes that whole day. Defaults to now.",
    )
    properties = PropertyFiltersField(
        required=False,
        help_text=f"Up to {api.MAX_PROPERTY_FILTERS} property filters as a JSON-encoded list. A trace is listed when one "
        "of its events matches every filter. Supported types are event, event_metadata, person, session, group, "
        "cohort and element, plus hogql, data_warehouse and data_warehouse_person_property, which need the "
        f"{QUERY_SCOPE} scope.",
    )
    filter_test_accounts = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Whether to leave out events from the project's test accounts. Defaults to the project's own "
        "setting for filtering test accounts.",
    )
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text="Text to look for in the inputs and outputs of the trace's generations and embeddings, ignoring "
        "case. Leading and trailing spaces are ignored, and a blank value searches nothing.",
    )
    view = serializers.ChoiceField(
        choices=api.QUICK_FILTERS,
        required=False,
        help_text="Lists only traces with an error, or only traces with user feedback. The counts ignore it.",
    )
    person_id = serializers.UUIDField(
        required=False,
        help_text="Lists only traces whose events belong to the person with this UUID.",
    )
    group_key = serializers.CharField(
        required=False,
        help_text="Lists only traces whose events belong to the group with this key. Send it with group_type_index.",
    )
    group_type_index = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=GROUP_TYPES_LIMIT - 1,
        help_text=f"The index of the group type that group_key belongs to, from 0 to {GROUP_TYPES_LIMIT - 1}. "
        "Send it with group_key.",
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
    cursor = serializers.CharField(
        required=False,
        help_text="The nextCursor of the previous page, to read the page after it. Leave it out for the first page.",
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
    limit = serializers.IntegerField(
        min_value=1,
        max_value=api.TRACE_LIST_MAX_LIMIT,
        default=api.TRACE_LIST_DEFAULT_LIMIT,
        help_text=f"How many traces a page holds, from 1 to {api.TRACE_LIST_MAX_LIMIT}. "
        f"Defaults to {api.TRACE_LIST_DEFAULT_LIMIT}.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if ("group_key" in attrs) != ("group_type_index" in attrs):
            raise serializers.ValidationError("Send group_key and group_type_index together.")
        return attrs


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
        if filters_need_query_scope(query.get("properties", ())) and scopes_caller_lacks(request, [QUERY_SCOPE]):
            raise PermissionDenied(QUERY_SCOPE_REQUIRED)
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
            properties=query.get("properties", ()),
            filter_test_accounts=query["filter_test_accounts"],
            include_support_traces=is_impersonated(request),
            search=query.get("search") or None,
            person_id=str(query["person_id"]) if "person_id" in query else None,
            group=api.TraceGroupScope(key=query["group_key"], type_index=query["group_type_index"])
            if "group_key" in query
            else None,
            quick_filter=query.get("view"),
        )
