import json
from pathlib import Path
from typing import Dict

import structlog
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.dashboard_templates import DashboardTemplate
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission

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
            "team_id",
            "public",
        ]

    def create(self, validated_data: Dict, *args, **kwargs) -> DashboardTemplate:
        if not validated_data["tiles"]:
            raise ValidationError(detail="You need to provide tiles for the template.")

        validated_data["team_id"] = self.context["team_id"]
        return super().create(validated_data, *args, **kwargs)


class DashboardTemplateViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
        OnlyStaffCanEditDashboardTemplate,
    ]
    serializer_class = DashboardTemplateSerializer

    @method_decorator(cache_page(60 * 2))  # cache for 2 minutes
    @action(methods=["GET"], detail=False)
    def json_schema(self, request: request.Request, **kwargs) -> response.Response:
        # Could switch from this being a static file to being dynamically generated from the serializer
        return response.Response(dashboard_template_schema)

    def get_queryset(self, *args, **kwargs):
        return DashboardTemplate.objects.filter(Q(team_id=self.team_id) | Q(public=True))
