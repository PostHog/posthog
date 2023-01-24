import json
from datetime import timedelta
from typing import Dict, List

import requests
import structlog
from rest_framework import request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.cache_utils import cache_for
from posthog.models.dashboard_templates import DashboardTemplate
from posthog.permissions import ProjectMembershipNecessaryPermissions

logger = structlog.get_logger(__name__)


class DashboardTemplateSerializer(serializers.Serializer):
    name: serializers.CharField = serializers.CharField(write_only=True, required=True)
    url: serializers.CharField = serializers.CharField(write_only=True, required=True)

    def create(self, validated_data: Dict, *args, **kwargs) -> DashboardTemplate:
        try:
            github_response = requests.get(validated_data["url"])
            template: Dict = github_response.json()
        except Exception as e:
            logger.error(
                "dashboard_templates.api.could_not_load_template_from_github",
                validated_data=validated_data,
                exc_info=True,
            )
            raise ValidationError(f"Could not load template from GitHub. {e}")

        if "template_name" not in template or template["template_name"] != validated_data["name"]:
            raise ValidationError(
                detail=f'The requested template "{validated_data["name"]}" does not match the requested template URL which loaded the template "{template["template_name"]}"'
            )

        return DashboardTemplate.objects.create(team_id=validated_data["team_id"], **template)


class DashboardTemplateViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
    ]
    serializer_class = DashboardTemplateSerializer

    def create(self, request: request.Request, **kwargs) -> response.Response:
        serializer = DashboardTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(team_id=self.team_id)
        return response.Response(data="", status=status.HTTP_200_OK)

    @action(methods=["GET"], detail=False)
    def repository(self, request: request.Request, **kwargs) -> response.Response:
        loaded_templates = self._load_repository_listing()

        installed_templates = self._current_installed_templates()

        annotated_templates = []
        for template in loaded_templates:
            if template["name"] in installed_templates:
                annotated_templates.append({**template, "installed": True})
            else:
                annotated_templates.append({**template, "installed": False})

        return response.Response(annotated_templates)

    @cache_for(timedelta(seconds=5))
    def _load_repository_listing(self) -> List[Dict]:
        """
        The repository in GitHub will change infrequently,
        there is no point loading it over-the-wire on every request
        """
        url = "https://raw.githubusercontent.com/PostHog/templates-repository/main/dashboards/dashboards.json"
        loaded_templates: List[Dict] = json.loads(requests.get(url).text)
        return loaded_templates

    @staticmethod
    def _current_installed_templates() -> List[str]:
        installed_templates: List[str] = [
            x for x in DashboardTemplate.objects.values_list("template_name", flat=True).all() if x
        ]
        installed_templates.append(str(DashboardTemplate.original_template().template_name))
        return installed_templates
