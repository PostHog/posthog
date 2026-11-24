from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import api, contracts
from .trace_page import PAGE_BOUNDS_BAD_REQUEST, TracePageWithBoundsRequestSerializer
from .trace_resource import THROTTLED_RESPONSE, TraceResourceViewSet


class TraceSentimentViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["create"]

    @validated_request(
        request_serializer=TracePageWithBoundsRequestSerializer,
        responses={
            200: OpenApiResponse(response=contracts.TraceSentimentList),
            400: PAGE_BOUNDS_BAD_REQUEST,
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_sentiment_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The sentiment of each trace on a page, from its sentiment evaluation results."""
        body = request.validated_data
        sentiments = self._read(
            request,
            lambda user, _hint: api.load_trace_sentiments(
                self.team,
                user,
                body["trace_ids"],
                earliest=body["earliest_created_at"],
                latest=body["latest_created_at"],
            ),
        )
        return Response(sentiments.model_dump(mode="json", by_alias=True))
