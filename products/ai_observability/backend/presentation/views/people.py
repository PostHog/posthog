from typing import Any
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import serializers, status
from rest_framework.response import Response

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination
from posthog.errors import ExposedCHQueryError
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team
from posthog.paging import Page, PageRequest

from ...facade import api, people, people_contracts
from .list_filters import (
    SelectionFilterQuerySerializer,
    TraceDateRangeQuerySerializer,
    group_scope_field,
    page_limit_field,
    property_filters_field,
    require_query_scope_for_filters,
    selection_filters,
)
from .property_filters import QUERY_SCOPE
from .trace_resource import THROTTLED_RESPONSE, TraceResourceViewSet

# The page read keeps every row up to the page's end in memory, so a deep offset is refused.
MAX_OFFSET = 10_000


class PeoplePagination(FacadeLimitOffsetPagination):
    default_limit = 50
    max_limit = 100

    def get_next_link(self) -> str | None:
        # The offset param refuses a page past MAX_OFFSET, so no link points at one.
        if (self.offset or 0) + (self.limit or 0) > MAX_OFFSET:
            return None
        return super().get_next_link()


class PeopleSelectionQuerySerializer(SelectionFilterQuerySerializer):
    properties = property_filters_field(
        "A person is listed when one of their events in range matches every filter, and their row counts only such "
        "events."
    )
    person_id = serializers.UUIDField(
        required=False,
        help_text="Lists only the person with this UUID.",
    )
    group_key = group_scope_field("people whose events")
    person_search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text="Text to look for in the distinct ids of each person's AI events in the date range and in their "
        "display name properties, ignoring case. Leading and trailing spaces are ignored, and a blank value searches nothing.",
    )
    include_anonymous = serializers.BooleanField(
        default=False,
        help_text="Whether to list anonymous people, whose events carry the trace id as their distinct id.",
    )


class PeopleListQuerySerializer(PeopleSelectionQuerySerializer):
    order = serializers.ChoiceField(
        choices=people.PeopleOrder.choices,
        default=people.PeopleOrder.LAST_SEEN,
        help_text="last_seen lists the most recently seen people first, and cost lists the people whose events cost "
        "the most first, with unknown costs last. Ties go by person id.",
    )
    view = serializers.ChoiceField(
        choices=people.PeopleView.choices,
        required=False,
        help_text=f"Lists only people with no AI activity in the {people.LOOKBACK.days} days before the range starts, "
        "a slower read. The response's count follows the view, and its counts field does not.",
    )
    limit = page_limit_field("people", default=PeoplePagination.default_limit, maximum=PeoplePagination.max_limit)
    offset = serializers.IntegerField(
        min_value=0,
        max_value=MAX_OFFSET,
        default=0,
        help_text=f"How many people to skip before the page starts, from 0 to {MAX_OFFSET}. Defaults to 0.",
    )


class PersonQuerySerializer(TraceDateRangeQuerySerializer):
    properties = property_filters_field("The person's row counts only their events that match every filter.")


PERSON_ID_PARAMETER = OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH, description="The person's UUID.")


class PeopleViewSet(TraceResourceViewSet):
    lookup_value_regex = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

    @validated_request(
        query_serializer=PeopleListQuerySerializer,
        responses={
            200: OpenApiResponse(response=people_contracts.PersonList),
            400: OpenApiResponse(description="A parameter, the date range or a property filter is invalid."),
            403: OpenApiResponse(
                description=f"The key lacks a required scope, or a property filter needs the {QUERY_SCOPE} scope."
            ),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_people_list",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The people with AI events in a date range, a page at a time, with how many of them are new and how many
        are anonymous. Labels use the project's display name properties."""
        query = request.validated_query_data
        require_query_scope_for_filters(request, query)
        paginator = PeoplePagination()
        built: list[people_contracts.PersonPage] = []
        try:
            people_query = self._people_query(request)

            def fetch(page: PageRequest) -> Page[people_contracts.PersonListItem]:
                build = self._read(
                    request, lambda user, _hint: people.load_people_list(self.team, user, people_query, page)
                )
                # Built after the query slot is released, so building a page never holds the team's slot.
                person_page = build()
                built.append(person_page)
                return Page(results=person_page.results, count=person_page.count)

            page = paginator.read_facade_page(request, fetch)
        except (
            api.InvalidTraceWindowError,
            api.InvalidTraceSelectionError,
            ExposedHogQLError,
            ExposedCHQueryError,
        ) as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        response = paginator.get_paginated_response(
            [item.model_dump(mode="json", by_alias=True) for item in page.results]
        )
        [person_page] = built
        response.data.update(person_page.model_dump(mode="json", by_alias=True, exclude={"count", "results"}))
        return response

    @validated_request(
        query_serializer=PersonQuerySerializer,
        parameters=[PERSON_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=people_contracts.PersonListItem),
            400: OpenApiResponse(description="The date range or a property filter is invalid."),
            403: OpenApiResponse(
                description=f"The key lacks a required scope, or a property filter needs the {QUERY_SCOPE} scope."
            ),
            404: OpenApiResponse(description="The person has no event in the date range under the filters."),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_people_retrieve",
    )
    def retrieve(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """One person's row in a date range, as the people list shows it, whether or not they are anonymous."""
        query = request.validated_query_data
        require_query_scope_for_filters(request, query)
        try:
            selection = api.TraceSelection(
                window=api.resolve_trace_window(self.team, query.get("date_from"), query.get("date_to")),
                properties=query.get("properties", ()),
                filter_test_accounts=query["filter_test_accounts"],
                include_support_traces=is_impersonated(request),
            )
            person = self._read(
                request, lambda user, _hint: people.get_person(self.team, user, selection, str(UUID(pk)))
            )
        except (
            api.InvalidTraceWindowError,
            api.InvalidTraceSelectionError,
            ExposedHogQLError,
            ExposedCHQueryError,
        ) as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        if person is None:
            return Response({"detail": "Person not found in this range."}, status=status.HTTP_404_NOT_FOUND)
        return Response(person.model_dump(mode="json", by_alias=True))

    def _people_query(self, request: ValidatedRequest) -> people.PeopleQuery:
        query = request.validated_query_data
        return people.PeopleQuery(
            selection=people_selection(self.team, request),
            order=people.PeopleOrder(query["order"]),
            include_anonymous=query["include_anonymous"],
            new_only=query.get("view") == people.PeopleView.NEW,
            person_search=query.get("person_search") or None,
        )


def people_selection(team: Team, request: ValidatedRequest) -> api.TraceSelection:
    query = request.validated_query_data
    return api.TraceSelection(
        window=api.resolve_trace_window(team, query.get("date_from"), query.get("date_to")),
        include_support_traces=is_impersonated(request),
        **selection_filters(query),
    )
