from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import status
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
from .session_resource import SESSION_ID_PARAMETER, SessionQuerySerializer, SessionResourceViewSet
from .trace_resource import THROTTLED_RESPONSE, request_user


class SessionListQuerySerializer(ListFilterQuerySerializer):
    properties = property_filters_field(
        "A session is listed when one of its traces has an event that matches every filter."
    )
    search = search_field("the generations and embeddings of the session's traces")
    person_id = person_scope_field("sessions with a trace whose events")
    group_key = group_scope_field("sessions with a trace whose events")
    limit = page_limit_field("sessions", default=api.SESSION_LIST_DEFAULT_LIMIT, maximum=api.SESSION_LIST_MAX_LIMIT)


class SessionViewSet(SessionResourceViewSet):
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
        session's facts cover all of it that the AI events retention holds, not only the traces in the range. Titles
        and people are the sessions' previews and people."""
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
            400: OpenApiResponse(description="The timestamp hint or the session id can't be read."),
            404: OpenApiResponse(description="No session with this id in the project."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_sessions_retrieve",
    )
    def retrieve(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """One session with its facts, read over the window its turns are read in, for a direct link with no list row
        to read it from."""
        session_id = self.session_id
        session = self._read(
            request,
            lambda user, hint: api.get_session(
                self.team, user, session_id, timestamp_hint=hint, include_support_traces=is_impersonated(request)
            ),
        )
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(session.model_dump(mode="json", by_alias=True))
