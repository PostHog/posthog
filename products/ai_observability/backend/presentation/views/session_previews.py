from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.helpers.impersonation import is_impersonated

from ...facade import api, contracts
from .session_page import SESSION_PAGE_BAD_REQUEST, SessionPageRequestSerializer
from .trace_page import ConversationReadThrottled
from .trace_resource import THROTTLED_RESPONSE, TraceResourceViewSet


class SessionPreviewsViewSet(ConversationReadThrottled, TraceResourceViewSet):
    scope_object_read_actions = ["create"]

    @validated_request(
        request_serializer=SessionPageRequestSerializer,
        responses={
            200: OpenApiResponse(response=contracts.SessionPreviewList),
            400: SESSION_PAGE_BAD_REQUEST,
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_sessions_previews_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The titles of a page of sessions: the user's message each session's first trace answered. A read, sent as a
        POST because a page of session ids may not fit in a query string."""
        build = self._read(
            request,
            lambda user, _hint: api.load_session_previews(
                self.team,
                user,
                request.validated_data["session_ids"],
                include_support_traces=is_impersonated(request),
            ),
        )
        # Built after the query slot is released, so normalizing a page of titles never holds the team's slot.
        return Response(build().model_dump(mode="json", by_alias=True))
