from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import api, contracts
from .trace_page import PAGE_BOUNDS_BAD_REQUEST, TracePageWithBoundsRequestSerializer
from .trace_resource import THROTTLED_RESPONSE, TraceResourceViewSet


class TracePeopleViewSet(TraceResourceViewSet):
    scope_object_read_actions = ["create"]

    @validated_request(
        request_serializer=TracePageWithBoundsRequestSerializer,
        responses={
            200: OpenApiResponse(response=contracts.TracePeopleList),
            400: PAGE_BOUNDS_BAD_REQUEST,
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_people_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The person each trace on a page ran for, labeled by the project's display name properties."""
        body = request.validated_data
        people = self._read(
            request,
            lambda user, _hint: api.load_trace_people(
                self.team,
                user,
                body["trace_ids"],
                earliest=body["earliest_created_at"],
                latest=body["latest_created_at"],
            ),
        )
        return Response(people.model_dump(mode="json", by_alias=True))
