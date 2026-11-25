from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.helpers.impersonation import is_impersonated

from ...facade import api, people, people_contracts
from .list_filters import TraceDateRangeQuerySerializer
from .trace_page import ConversationReadThrottled
from .trace_resource import THROTTLED_RESPONSE, TraceResourceViewSet

PEOPLE_FIRST_SEEN_MAX_IDS = 100


class PeopleFirstSeenRequestSerializer(TraceDateRangeQuerySerializer):
    person_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=PEOPLE_FIRST_SEEN_MAX_IDS,
        help_text=f"The UUIDs of the people on a page of the list, from 1 to {PEOPLE_FIRST_SEEN_MAX_IDS}. Items come "
        "back in this order, once per person.",
    )


class PeopleFirstSeenViewSet(ConversationReadThrottled, TraceResourceViewSet):
    scope_object_read_actions = ["create"]

    @validated_request(
        request_serializer=PeopleFirstSeenRequestSerializer,
        responses={
            200: OpenApiResponse(response=people_contracts.PersonFirstSeenList),
            400: OpenApiResponse(
                description="The person IDs are missing, too many or not UUIDs, or the range is invalid."
            ),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_people_first_seen_create",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """When each person on a page was first seen, from the lookback bound to the end of the date range. A read,
        sent as a POST because a page of ids may not fit in a query string."""
        body = request.validated_data
        try:
            selection = api.TraceSelection(
                window=api.resolve_trace_window(self.team, body.get("date_from"), body.get("date_to")),
                filter_test_accounts=body["filter_test_accounts"],
                include_support_traces=is_impersonated(request),
            )
        except api.InvalidTraceWindowError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        first_seen = self._read(
            request,
            lambda user, _hint: people.load_people_first_seen(
                self.team, user, selection, [str(person_id) for person_id in body["person_ids"]]
            ),
        )
        return Response(first_seen.model_dump(mode="json", by_alias=True))
