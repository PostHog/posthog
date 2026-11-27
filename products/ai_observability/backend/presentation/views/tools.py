from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import diagnostics
from ...facade.diagnostics_contracts import ToolGroupDetail, ToolList
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


class ToolSelectionQuerySerializer(SelectionFilterQuerySerializer):
    properties = property_filters_field("Tools are read from the traces where one event matches every filter.")
    group_key = group_scope_field("tools from traces whose events")


class ToolListQuerySerializer(ToolSelectionQuerySerializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text="Text to look for in the tool name, ignoring case. It narrows the counts too. Leading and trailing "
        "spaces are ignored, and a blank value searches nothing.",
    )
    view = serializers.ChoiceField(
        choices=diagnostics.ToolView.choices,
        required=False,
        help_text="Lists only the failing tools. The counts ignore it.",
    )
    order = serializers.ChoiceField(
        choices=diagnostics.ToolOrder.choices,
        required=False,
        help_text="Sorts the tools, largest first, by calls, by change from the previous period, by traces, by "
        "failure rate, or by the latest call. Tools with no captured result sort last by failure rate. Defaults to "
        "calls.",
    )
    limit = page_limit_field(
        "tools", default=DIAGNOSTICS_PAGE_DEFAULT_LIMIT, maximum=diagnostics.DIAGNOSTICS_PAGE_MAX_LIMIT
    )
    offset = page_offset_field("tools", maximum=diagnostics.DIAGNOSTICS_PAGE_MAX_OFFSET)


class ToolViewSet(DiagnosticsViewSet):
    not_found_errors = (diagnostics.ToolNotFoundError,)

    @validated_request(
        query_serializer=ToolListQuerySerializer,
        responses={
            200: OpenApiResponse(response=ToolList),
            400: OpenApiResponse(description="A parameter, the date range or a property filter is invalid."),
            403: SCOPE_RESPONSE,
            422: RANGE_TOO_LONG_RESPONSE,
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_tools_list",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The tools that the project's generations call in a date range, a page at a time. Each tool says how its
        calls moved from the period of the same length before the range, and how often its captured results
        failed."""
        query = request.validated_query_data
        selection = self._selection(request)
        return self._page_response(
            request,
            lambda user, page: diagnostics.load_tool_list(
                self.team,
                user,
                selection,
                search=query.get("search"),
                view=diagnostics.ToolView(query["view"]) if "view" in query else None,
                order=diagnostics.ToolOrder(query["order"]) if "order" in query else None,
                page=page,
            ),
            ToolList,
        )

    @validated_request(
        query_serializer=ToolSelectionQuerySerializer,
        parameters=[entity_key_parameter("tool", "tools")],
        responses={
            200: OpenApiResponse(response=ToolGroupDetail),
            400: OpenApiResponse(description="The key, a parameter, the date range or a property filter is invalid."),
            403: SCOPE_RESPONSE,
            404: OpenApiResponse(description="No generation calls the tool in the date range."),
            422: RANGE_TOO_LONG_RESPONSE,
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_tools_retrieve",
    )
    def retrieve(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        """One tool over a date range, as the tools list shows it, with its calls in the period before the range.
        Send the filters of the list it came from, so the two agree."""
        selection = self._selection(request)
        build = self._read(request, lambda user: diagnostics.get_tool(self.team, user, selection, pk))
        # Built after the query slot is released, so building the tool never holds the team's slot.
        return Response(build().model_dump(mode="json", by_alias=True))
