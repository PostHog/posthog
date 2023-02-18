import json
from typing import Dict, List

import requests
import structlog
from rest_framework import request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.logging.timing import timed
from posthog.models.dashboard_templates import DashboardTemplate
from posthog.permissions import ProjectMembershipNecessaryPermissions

logger = structlog.get_logger(__name__)


class DashboardTemplateSerializer(serializers.Serializer):
    name: serializers.CharField = serializers.CharField(write_only=True, required=False)
    url: serializers.CharField = serializers.CharField(write_only=True, required=False)

    template_name: serializers.CharField = serializers.CharField(required=False)
    dashboard_description: serializers.CharField = serializers.CharField(required=False)
    dashboard_filters: serializers.JSONField = serializers.JSONField(required=False)
    tags: serializers.ListField = serializers.ListField(required=False)
    tiles: serializers.JSONField = serializers.JSONField(required=False)
    variables: serializers.JSONField = serializers.JSONField(required=False)

    def create(self, validated_data: Dict, *args, **kwargs) -> DashboardTemplate:
        if "url" in validated_data:
            # name required
            if not validated_data["name"]:
                raise ValidationError(detail="You need to provide a name for the template.")
            try:
                github_response = requests.get(validated_data["url"])
                template: Dict = github_response.json()
                template["github_url"] = validated_data["url"]
            except Exception as e:
                logger.error(
                    "dashboard_templates.api.could_not_load_template_from_github",
                    validated_data=validated_data,
                    exc_info=True,
                )
                raise ValidationError(f"Could not load template from GitHub. {e}")

            if "template_name" not in template or template["template_name"] != validated_data["name"]:
                raise ValidationError(
                    detail=f'The requested template "{validated_data["name"]}" does not match the requested template URL which loaded the template "{template.get("template_name", "no template name loaded from github")}"'
                )

            return DashboardTemplate.objects.update_or_create(
                team_id=None, template_name=template.get("template_name"), defaults=template
            )[0]
        else:
            if not validated_data["tiles"]:
                raise ValidationError(detail="You need to provide tiles for the template.")

            return DashboardTemplate.objects.update_or_create(
                team_id=None,
                defaults=validated_data,
            )[0]


class DashboardTemplateViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
    ]
    serializer_class = DashboardTemplateSerializer

    def create(self, request: request.Request, **kwargs) -> response.Response:
        if not request.user.is_staff:
            return response.Response(status=status.HTTP_403_FORBIDDEN)

        serializer = DashboardTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(data="", status=status.HTTP_200_OK)

    def list(self, request: request.Request, **kwargs) -> response.Response:
        return response.Response(DashboardTemplate.objects.filter(team_id=None).values())

    @timed("dashboard_templates.api_repository_load")
    @action(methods=["GET"], detail=False)
    def repository(self, request: request.Request, **kwargs) -> response.Response:
        loaded_templates = self._load_repository_listing()

        installed_templates = self._current_installed_templates()

        annotated_templates = []
        for template in loaded_templates:
            is_installed = template["name"] in installed_templates.keys()

            has_new_version = False
            if is_installed and template.get("url"):
                installed_url = installed_templates.get(template["name"], None)
                if installed_url:
                    has_new_version = template["url"] != installed_url

            annotated_templates.append({**template, "installed": is_installed, "has_new_version": has_new_version})

        return response.Response(annotated_templates)

    @staticmethod
    def _load_repository_listing() -> List[Dict]:
        url = "https://raw.githubusercontent.com/PostHog/templates-repository/main/dashboards/dashboards.json"
        loaded_templates: List[Dict] = json.loads(requests.get(url).text)
        return [
            # The OG template is hard-coded, not served by the repository,
            # because it is used in tests and in team setup, so we need to make sure it's always there.
            # It is added in to the template listing here
            {
                "name": "Product analytics",
                "url": None,
                "description": "The OG PostHog product analytics dashboard template",
                "verified": True,
                "maintainer": "official",
            }
        ] + loaded_templates

    @staticmethod
    def _current_installed_templates() -> Dict[str, str]:
        installed_templates = {
            dt.template_name: dt.github_url
            for dt in DashboardTemplate.objects.only("template_name", "github_url").all()
        }

        if DashboardTemplate.original_template().template_name not in installed_templates:
            installed_templates[DashboardTemplate.original_template().template_name] = None

        return installed_templates
