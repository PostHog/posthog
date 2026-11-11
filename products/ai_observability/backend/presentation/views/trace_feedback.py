from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import status
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.permissions import get_authenticator_scopes
from posthog.scopes import scopes_not_covered

from ...facade import api, contracts
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment
from .trace_resource import THROTTLED_RESPONSE, TRACE_ID_PARAMETER, TraceQuerySerializer, TraceResourceViewSet

SURVEY_RESPONSE_SCOPES = ["survey:read", "query:read"]


def _token_allows(request: ValidatedRequest, required_scopes: list[str]) -> bool:
    """True for session auth, which carries no scopes."""
    scopes = get_authenticator_scopes(getattr(request, "successful_authenticator", None))
    return scopes is None or "*" in scopes or not scopes_not_covered(scopes, required_scopes)


class TraceFeedbackViewSet(TraceResourceViewSet):
    @validated_request(
        query_serializer=TraceQuerySerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TraceFeedback),
            400: OpenApiResponse(description="The timestamp hint or the encoded trace id is malformed."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_feedback_retrieve",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """End-user feedback on a trace: scores and comments from its feedback events, survey responses linked to it, and surveys shown but not answered."""
        try:
            trace_id = decode_trace_id_segment(self.trace_segment)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        # Survey responses are survey data, so a token also needs the scopes the survey responses endpoint requires.
        include_surveys = _token_allows(request, SURVEY_RESPONSE_SCOPES)
        feedback = self._read(
            request,
            lambda user, hint: api.get_trace_feedback(self.team, user, trace_id, hint, include_surveys=include_surveys),
        )
        return Response(feedback.model_dump(mode="json", by_alias=True))
