from datetime import datetime
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
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
    check_one_page_position,
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
from .trace_resource import THROTTLED_RESPONSE, TraceResourceViewSet, request_user

SESSION_ID_PARAMETER = OpenApiParameter(
    "id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="The session id, sent as the unpadded base64url encoding of its UTF-8 bytes.",
)


def _malformed_session_id() -> Response:
    return Response({"detail": "Malformed encoded session id."}, status=status.HTTP_400_BAD_REQUEST)


class SessionListQuerySerializer(ListFilterQuerySerializer):
    properties = property_filters_field(
        "A session is listed when one of its traces has an event that matches every filter."
    )
    search = search_field("the generations and embeddings of the session's traces")
    person_id = person_scope_field("sessions with a trace whose events")
    group_key = group_scope_field("sessions with a trace whose events")
    limit = page_limit_field("sessions", default=api.SESSION_LIST_DEFAULT_LIMIT, maximum=api.SESSION_LIST_MAX_LIMIT)


class SessionQuerySerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField(
        required=False,
        help_text="When the session's first turn happened, as carried by links into it. Lets a session older than "
        "the AI events retention load from the shared events table.",
    )

    def validate_timestamp(self, value: datetime) -> datetime:
        if not api.is_usable_timestamp_hint(value):
            raise serializers.ValidationError("Timestamp is out of range.")
        return value


class SessionTurnsQuerySerializer(SessionQuerySerializer):
    cursor = serializers.CharField(
        required=False,
        help_text="The nextCursor of a page, to read the page after it. Leave out cursor, before_cursor and around "
        "for the session's first page.",
    )
    before_cursor = serializers.CharField(
        required=False,
        help_text="The previousCursor of a page, to read the page before it. Send only one of cursor, before_cursor "
        "and around.",
    )
    around = serializers.CharField(
        required=False,
        help_text="A trace id, to read the page that holds that turn with the turns before it. A trace outside the "
        "session reads the first page. Send only one of cursor, before_cursor and around.",
    )
    limit = page_limit_field("turns", default=api.SESSION_TURNS_PAGE_SIZE, maximum=api.SESSION_TURNS_PAGE_SIZE)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        check_one_page_position(attrs)
        return attrs


class SessionViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["list", "retrieve", "turns"]

    @validated_request(
        query_serializer=SessionListQuerySerializer,
        responses={
            200: OpenApiResponse(response=contracts.SessionList),
            400: OpenApiResponse(
                description="A parameter, the cursor, the date range or a property filter is invalid."
            ),
            403: OpenApiResponse(
                description=f"The key lacks a required scope, or a property filter needs the {QUERY_SCOPE} scope."
            ),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_sessions_list",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The project's sessions that have a trace in a date range, newest activity first, a page at a time. Each
        session's facts cover the whole session, not only the traces in the range."""
        query = request.validated_query_data
        require_query_scope_for_filters(request, query)
        user = request_user(request)
        try:
            selection = api.TraceSelection(
                window=api.resolve_trace_window(self.team, query.get("date_from"), query.get("date_to")),
                include_support_traces=is_impersonated(request),
                **selection_filters(query),
            )
            build = self._read(
                request,
                lambda _user, _hint: api.load_session_list(
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
        return Response(build().model_dump(mode="json", by_alias=True))

    @validated_request(
        query_serializer=SessionQuerySerializer,
        parameters=[SESSION_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.SessionListItem),
            400: OpenApiResponse(description="The timestamp or the encoded session id is malformed."),
            404: OpenApiResponse(description="No session with this id in the project."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_sessions_retrieve",
    )
    def retrieve(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """One session with its facts over its whole extent, for a direct link with no list row to read it from."""
        try:
            session_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return _malformed_session_id()
        session = self._read(
            request,
            lambda user, _hint: api.get_session(
                self.team,
                user,
                session_id,
                hint=request.validated_query_data.get("timestamp"),
                include_support_traces=is_impersonated(request),
            ),
        )
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(session.model_dump(mode="json", by_alias=True))

    @validated_request(
        query_serializer=SessionTurnsQuerySerializer,
        parameters=[SESSION_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.SessionTurnPage),
            400: OpenApiResponse(
                description="A parameter, the cursor, the timestamp or the encoded session id is invalid."
            ),
            404: OpenApiResponse(description="No session with this id in the project."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_sessions_turns_retrieve",
    )
    @action(detail=True, methods=["GET"])
    def turns(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """The session's conversation a page of turns at a time, in session order and in either direction: each trace
        with what it added to the conversation and the answer it gave, ready to render."""
        try:
            session_id = decode_trace_id_segment(pk)
        except MalformedTraceIdSegmentError:
            return _malformed_session_id()
        query = request.validated_query_data
        user = request_user(request)
        try:
            build = self._read(
                request,
                lambda _user, _hint: api.load_session_turns(
                    self.team,
                    user,
                    session_id,
                    hint=query.get("timestamp"),
                    include_support_traces=is_impersonated(request),
                    cursor=query.get("cursor"),
                    before_cursor=query.get("before_cursor"),
                    around=query.get("around"),
                    limit=query["limit"],
                ),
            )
        except api.InvalidTraceCursorError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        if build is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        # Built after the query slot is released, so normalizing a page of turns never holds the team's slot.
        return Response(build().model_dump(mode="json", by_alias=True))
