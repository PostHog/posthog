from rest_framework import viewsets
from rest_framework.decorators import action

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.activity_logging.activity_log import (
    load_all_activity,
)
from rest_framework import request


class DataManagementViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    @action(methods=["GET"], url_path="activity", detail=False)
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_all_activity(
            scope_list=["EventDefinition", "PropertyDefinition"],
            team_id=request.user.team.id,  # type: ignore
            limit=limit,
            page=page,
        )

        return activity_page_response(activity_page, limit, page, request)
