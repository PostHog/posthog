from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.helpers.impersonation import is_impersonated

from ...facade import api, contracts
from .list_filters import check_one_page_position, page_limit_field
from .session_resource import SESSION_ID_PARAMETER, SessionQuerySerializer, SessionResourceViewSet
from .trace_page import ConversationReadThrottled
from .trace_resource import THROTTLED_RESPONSE, request_user


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
        max_length=1000,
        trim_whitespace=False,
        help_text="A trace id, to read the page that holds that turn with the turns before it. A trace outside the "
        "session reads the first page. Send only one of cursor, before_cursor and around.",
    )
    limit = page_limit_field("turns", default=api.SESSION_TURNS_PAGE_SIZE, maximum=api.SESSION_TURNS_PAGE_SIZE)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        check_one_page_position(attrs)
        return attrs


class SessionTurnsViewSet(ConversationReadThrottled, SessionResourceViewSet):
    @validated_request(
        query_serializer=SessionTurnsQuerySerializer,
        parameters=[SESSION_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.SessionTurnPage),
            400: OpenApiResponse(
                description="A parameter, the cursor, the timestamp hint or the session id is invalid."
            ),
            404: OpenApiResponse(description="No session with this id in the project."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_sessions_turns_retrieve",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The session's traces a page at a time, one per turn, oldest first and in either direction. The session is
        read over the AI events retention, or with an older timestamp hint, from just before the hint."""
        session_id = self.session_id
        query = request.validated_query_data
        user = request_user(request)
        try:
            build = self._read(
                request,
                lambda _user, hint: api.load_session_turns(
                    self.team,
                    user,
                    session_id,
                    timestamp_hint=hint,
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
        # Built after the query slot is released, so reading review states never holds the team's slot.
        return Response(build().model_dump(mode="json", by_alias=True))
