from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import api, contracts
from .trace_page import PAGE_BOUNDS_BAD_REQUEST, TraceTurnsRequestSerializer
from .trace_resource import THROTTLED_RESPONSE, TraceResourceViewSet


class TraceTurnsViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["create"]

    @validated_request(
        request_serializer=TraceTurnsRequestSerializer,
        responses={
            200: OpenApiResponse(response=contracts.TraceTurnList),
            400: PAGE_BOUNDS_BAD_REQUEST,
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_turns_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The turns of a page of traces: what each trace added to its conversation, with the answer it gave."""
        data = request.validated_data
        build = self._read(
            request,
            lambda user, _hint: api.load_trace_turns(
                self.team,
                user,
                data["trace_ids"],
                earliest=data["earliest_created_at"],
                latest=data["latest_created_at"],
            ),
        )
        # Built after the query slot is released, so normalizing a page of turns never holds the team's slot.
        return Response(build().model_dump(mode="json", by_alias=True))
