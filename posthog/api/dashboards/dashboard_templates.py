import json
from pathlib import Path
from typing import Dict, List

import requests
import structlog
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.logging.timing import timed
from posthog.models.dashboard_templates import DashboardTemplate

logger = structlog.get_logger(__name__)

# load dashboard_template_schema.json
dashboard_template_schema = json.loads((Path(__file__).parent / "dashboard_template_schema.json").read_text())


class OnlyStaffCanEditDashboardTemplate(BasePermission):
    message = "You don't have edit permissions for this dashboard template."

    def has_permission(self, request: Request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_staff


class DashboardTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardTemplate
        fields = [
            "id",
            "template_name",
            "dashboard_description",
            "dashboard_filters",
            "tags",
            "tiles",
            "variables",
            "deleted",
            "created_at",
            "created_by",
            "image_url",
            "name",  # TODO: remove
            "url",  # TODO: remove
        ]

    name: serializers.CharField = serializers.CharField(write_only=True, required=False)
    url: serializers.CharField = serializers.CharField(write_only=True, required=False)

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

            return DashboardTemplate.objects.create(
                team_id=None,
                template_name=validated_data["template_name"],
                dashboard_description=validated_data["dashboard_description"],
                dashboard_filters=validated_data["dashboard_filters"],
                tags=validated_data["tags"],
                tiles=validated_data["tiles"],
                variables=validated_data["variables"],
            )


class DashboardTemplateViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, OnlyStaffCanEditDashboardTemplate]
    serializer_class = DashboardTemplateSerializer

    def get_queryset(self):
        return DashboardTemplate.objects.filter(team_id=None)

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

    @method_decorator(cache_page(60 * 2))  # cache for 2 minutes
    @action(methods=["GET"], detail=False)
    def json_schema(self, request: request.Request, **kwargs) -> response.Response:
        # Could switch from this being a static file to being dynamically generated from the serializer
        return response.Response(dashboard_template_schema)
