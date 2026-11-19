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
    page_limit_field,
    require_query_scope_for_filters,
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


class SessionListQuerySerializer(ListFilterQuerySerializer):
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


class SessionViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["list", "retrieve", "availability"]

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
            return Response({"detail": "Malformed encoded session id."}, status=status.HTTP_400_BAD_REQUEST)
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
        responses={200: OpenApiResponse(response=contracts.SessionAvailability), 429: THROTTLED_RESPONSE},
        operation_id="ai_observability_sessions_availability",
    )
    @action(detail=False, methods=["GET"])
    def availability(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Whether the project has any AI event with a session id within the AI events retention."""
        availability = self._read(request, lambda user, _hint: api.has_sessions(self.team, user))
        return Response(availability.model_dump(mode="json", by_alias=True))
