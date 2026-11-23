from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import api, contracts
from .trace_page import TracePageRequestSerializer
from .trace_resource import THROTTLED_RESPONSE, TraceResourceViewSet


class TracePreviewsViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["create"]

    @validated_request(
        request_serializer=TracePageRequestSerializer,
        responses={
            200: OpenApiResponse(response=contracts.TracePreviewList),
            400: OpenApiResponse(description="The trace IDs are missing or too many."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_previews_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The input and output previews of a page of traces: the user's message each trace answered and its answer."""
        build = self._read(
            request, lambda user, _hint: api.load_trace_previews(self.team, user, request.validated_data["trace_ids"])
        )
        # Built after the query slot is released, so normalizing a page of previews never holds the team's slot.
        return Response(build().model_dump(mode="json", by_alias=True))
