import json

import requests
from rest_framework import request, response, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.permissions import ProjectMembershipNecessaryPermissions

dashboard_templates_repository_raw_url = (
    "https://raw.githubusercontent.com/PostHog/templates-repository/main/dashboards"
)


class DashboardTemplateViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
    ]

    @action(methods=["GET"], detail=False)
    def repository(self, request: request.Request, **kwargs):
        url = f"{dashboard_templates_repository_raw_url}/dashboards.json"
        templates = requests.get(url)
        return response.Response(json.loads(templates.text))
