import json
from typing import Dict, List

import requests
from rest_framework import request, response, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.dashboard_templates import DashboardTemplate
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
        loaded_templates: List[Dict] = json.loads(requests.get(url).text)
        annotated_templates = []
        installed_templates: List[str] = [
            x for x in DashboardTemplate.objects.values_list("template_name", flat=True).all()
        ]
        installed_templates.append(DashboardTemplate.original_template().get("template_name"))
        for template in loaded_templates:
            if template["name"] in installed_templates:
                annotated_templates.append({**template, "installed": True})
            else:
                annotated_templates.append({**template, "installed": False})

        return response.Response(annotated_templates)
