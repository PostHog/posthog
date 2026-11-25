from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import status
from rest_framework.response import Response

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.errors import ExposedCHQueryError

from ...facade import api, people, people_contracts
from .list_filters import require_query_scope_for_filters
from .people import PeopleSelectionQuerySerializer, people_selection
from .property_filters import QUERY_SCOPE
from .trace_resource import THROTTLED_RESPONSE, TraceResourceViewSet


class PeopleNewCountViewSet(TraceResourceViewSet):
    @validated_request(
        query_serializer=PeopleSelectionQuerySerializer,
        responses={
            200: OpenApiResponse(response=people_contracts.PeopleNewCount),
            400: OpenApiResponse(description="A parameter, the date range or a property filter is invalid."),
            403: OpenApiResponse(
                description=f"The key lacks a required scope, or a property filter needs the {QUERY_SCOPE} scope."
            ),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_people_new_count_retrieve",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """How many of the people the list shows for these parameters are new to the project's AI. Read apart from
        the list, after its rows, because it reads the days before the range."""
        query = request.validated_query_data
        require_query_scope_for_filters(request, query)
        try:
            selection = people_selection(self.team, request)
            new_count = self._read(
                request,
                lambda user, _hint: people.load_people_new_count(
                    self.team,
                    user,
                    selection,
                    include_anonymous=query["include_anonymous"],
                    person_search=query.get("person_search") or None,
                ),
            )
        except (
            api.InvalidTraceWindowError,
            api.InvalidTraceSelectionError,
            ExposedHogQLError,
            ExposedCHQueryError,
        ) as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(new_count.model_dump(mode="json", by_alias=True))
