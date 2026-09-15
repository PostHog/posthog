from rest_framework import request, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.activity_logging.activity_log import load_all_activity
from posthog.models.activity_logging.activity_page import activity_page_response, parse_activity_page_params


class DataManagementViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    @action(methods=["GET"], url_path="activity", detail=False, required_scopes=["activity_log:read"])
    def all_activity(self, request: request.Request, **kwargs):
        page_params = parse_activity_page_params(request)

        activity_page = load_all_activity(
            scope_list=["EventDefinition", "PropertyDefinition"],
            team_id=self.team.id,
            limit=page_params.limit,
            page=page_params.page,
        )

        return activity_page_response(activity_page, page_params.limit, page_params.page, request)
