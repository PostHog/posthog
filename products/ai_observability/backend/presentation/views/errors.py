from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import diagnostics
from ...facade.diagnostics_contracts import ErrorGroupDetail, ErrorList
from .diagnostics_resource import (
    DIAGNOSTICS_PAGE_DEFAULT_LIMIT,
    RANGE_TOO_LONG_RESPONSE,
    SCOPE_RESPONSE,
    DiagnosticsViewSet,
    entity_key_parameter,
)
from .list_filters import (
    SelectionFilterQuerySerializer,
    group_scope_field,
    page_limit_field,
    page_offset_field,
    property_filters_field,
)
from .trace_resource import THROTTLED_RESPONSE


class ErrorSelectionQuerySerializer(SelectionFilterQuerySerializer):
    properties = property_filters_field("Errors are read from the traces where one event matches every filter.")
    group_key = group_scope_field("errors from traces whose events")


class ErrorSearchQuerySerializer(ErrorSelectionQuerySerializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text="Text to look for in the error message, ignoring case. It narrows the counts too. Leading and "
        "trailing spaces are ignored, and a blank value searches nothing.",
    )


class ErrorListQuerySerializer(ErrorSearchQuerySerializer):
    view = serializers.ChoiceField(
        choices=diagnostics.ErrorView.choices,
        required=False,
        help_text="Lists only the increasing, the decreasing or the new errors. The counts ignore it.",
    )
    order = serializers.ChoiceField(
        choices=diagnostics.ErrorOrder.choices,
        required=False,
        help_text="Sorts the errors, largest first, by occurrences, by change from the previous period, by traces, "
        "by users, or by the latest occurrence. Defaults to occurrences.",
    )
    limit = page_limit_field(
        "errors", default=DIAGNOSTICS_PAGE_DEFAULT_LIMIT, maximum=diagnostics.DIAGNOSTICS_PAGE_MAX_LIMIT
    )
    offset = page_offset_field("errors", maximum=diagnostics.DIAGNOSTICS_PAGE_MAX_OFFSET)


class ErrorViewSet(DiagnosticsViewSet):
    not_found_errors = (diagnostics.ErrorNotFoundError,)

    @validated_request(
        query_serializer=ErrorListQuerySerializer,
        responses={
            200: OpenApiResponse(response=ErrorList),
            400: OpenApiResponse(description="A parameter, the date range or a property filter is invalid."),
            403: SCOPE_RESPONSE,
            422: RANGE_TOO_LONG_RESPONSE,
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_errors_list",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The errors of the project's AI events in a date range, grouped by normalized message, a page at a time.
        Each error says how it moved from the period of the same length before the range."""
        query = request.validated_query_data
        selection = self._selection(request)
        return self._page_response(
            request,
            lambda user, page: diagnostics.load_error_list(
                self.team,
                user,
                selection,
                search=query.get("search"),
                view=diagnostics.ErrorView(query["view"]) if "view" in query else None,
                order=diagnostics.ErrorOrder(query["order"]) if "order" in query else None,
                page=page,
            ),
            ErrorList,
        )

    @validated_request(
        query_serializer=ErrorSelectionQuerySerializer,
        parameters=[entity_key_parameter("error", "errors")],
        responses={
            200: OpenApiResponse(response=ErrorGroupDetail),
            400: OpenApiResponse(description="The key, a parameter, the date range or a property filter is invalid."),
            403: SCOPE_RESPONSE,
            404: OpenApiResponse(description="The error has no occurrence in the date range."),
            422: RANGE_TOO_LONG_RESPONSE,
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_errors_retrieve",
    )
    def retrieve(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """One error over a date range, as the errors list shows it, with its occurrences in the period before the
        range. Send the filters of the list it came from, so the two agree."""
        selection = self._selection(request)
        build = self._read(request, lambda user: diagnostics.get_error(self.team, user, selection, pk))
        # Built after the query slot is released, so building the error never holds the team's slot.
        return Response(build().model_dump(mode="json", by_alias=True))
