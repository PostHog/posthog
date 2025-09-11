from rest_framework import request, response, status

from posthog.models.activity_logging.activity_log import ActivityPage
from posthog.models.activity_logging.serializers import ActivityLogSerializer
from posthog.utils import format_query_params_absolute_url


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
