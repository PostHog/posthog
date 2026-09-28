from rest_framework import request, response, serializers, status

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityPage
from posthog.models.activity_logging.serializers import ActivityLogSerializer
from posthog.utils import format_query_params_absolute_url


class ActivityLogPaginatedResponseSerializer(serializers.Serializer):
    """Response shape for paginated activity log endpoints."""

    results = ActivityLogSerializer(many=True)
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    total_count = serializers.IntegerField()


class ActivityQueryParamsSerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, default=10, min_value=1, help_text="Number of items per page")
    page = serializers.IntegerField(required=False, default=1, min_value=1, help_text="Page number")


@frozen
class ActivityPageParams:
    limit: int
    page: int


def parse_activity_page_params(request: request.Request) -> ActivityPageParams:
    serializer = ActivityQueryParamsSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return ActivityPageParams(limit=serializer.validated_data["limit"], page=serializer.validated_data["page"])


def activity_page_response(
    activity_page: ActivityPage, limit: int, page: int, request: request.Request
) -> response.Response:
    return response.Response(
        {
            "results": ActivityLogSerializer(activity_page.results, many=True).data,
            "next": format_query_params_absolute_url(request, page + 1, limit, offset_alias="page")
            if activity_page.has_next
            else None,
            "previous": format_query_params_absolute_url(request, page - 1, limit, offset_alias="page")
            if activity_page.has_previous
            else None,
            "total_count": activity_page.total_count,
        },
        status=status.HTTP_200_OK,
    )
