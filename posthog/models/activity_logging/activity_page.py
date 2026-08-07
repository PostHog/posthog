import dataclasses

from rest_framework import request, response, serializers, status

from posthog.models.activity_logging.activity_log import ActivityPage
from posthog.models.activity_logging.serializers import ActivityLogSerializer
from posthog.utils import format_query_params_absolute_url


class ActivityLogPaginatedResponseSerializer(serializers.Serializer):
    """Response shape for paginated activity log endpoints."""

    results = ActivityLogSerializer(many=True)
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    total_count = serializers.IntegerField()


class ActivityPaginationParamsSerializer(serializers.Serializer):
    """Query params shared by activity log endpoints that hand-parse `limit` and `page`."""

    limit = serializers.IntegerField(required=False, default=10, min_value=1, help_text="Number of items per page")
    page = serializers.IntegerField(required=False, default=1, min_value=1, help_text="1-indexed page number")


@dataclasses.dataclass(frozen=True, kw_only=True)
class ActivityPaginationParams:
    limit: int
    page: int


def get_activity_pagination_params(request: request.Request) -> ActivityPaginationParams:
    """Parse `limit` and `page` query params, returning a 400 for non-numeric or out-of-bounds values.

    Guards the endpoints that would otherwise raise a 500 on `int(...)` when the caller passes
    something like `?page=abc` or `?limit=0`.
    """
    serializer = ActivityPaginationParamsSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return ActivityPaginationParams(limit=serializer.validated_data["limit"], page=serializer.validated_data["page"])


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
