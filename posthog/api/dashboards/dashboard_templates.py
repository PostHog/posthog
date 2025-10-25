import json
from pathlib import Path

from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

import structlog
from rest_framework import request, response, serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.helpers.full_text_search import build_rank
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
            "team_id",
            "scope",
            "availability_contexts",
        ]

    def create(self, validated_data: dict, *args, **kwargs) -> DashboardTemplate:
        if not validated_data["tiles"]:
            raise ValidationError(detail="You need to provide tiles for the template.")

        # default scope is team
        if not validated_data.get("scope"):
            validated_data["scope"] = DashboardTemplate.Scope.ONLY_TEAM

        validated_data["team_id"] = self.context["team_id"]
        return super().create(validated_data, *args, **kwargs)

    def update(self, instance: DashboardTemplate, validated_data: dict, *args, **kwargs) -> DashboardTemplate:
        # if the original request was to make the template scope to team only, and the template is none then deny the request
        if validated_data.get("scope") == "team" and instance.scope == "global" and not instance.team_id:
            raise ValidationError(detail="The original templates cannot be made private as they would be lost.")

        return super().update(instance, validated_data, *args, **kwargs)


class DashboardTemplateViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "dashboard_template"
    permission_classes = [OnlyStaffCanEditDashboardTemplate]
    serializer_class = DashboardTemplateSerializer
    queryset = DashboardTemplate.objects.all()

    @method_decorator(cache_page(60 * 2))  # cache for 2 minutes
    @action(methods=["GET"], detail=False)
    def json_schema(self, request: request.Request, **kwargs) -> response.Response:
        # Could switch from this being a static file to being dynamically generated from the serializer
        return response.Response(dashboard_template_schema)

    def dangerously_get_queryset(self):
        # NOTE: we use the dangerous version as we want to bypass the team/org scoping and do it here instead depending on the scope
        filters = self.request.GET.dict()
        scope = filters.pop("scope", None)
        search = filters.pop("search", None)

        # if scope is feature flag, then only return feature flag templates
        # they're implicitly global, so they are not associated with any teams
        if scope == DashboardTemplate.Scope.FEATURE_FLAG:
            query_condition = Q(scope=DashboardTemplate.Scope.FEATURE_FLAG)
        elif scope == DashboardTemplate.Scope.GLOBAL:
            query_condition = Q(scope=DashboardTemplate.Scope.GLOBAL)
        # otherwise we are in the new dashboard context so show global templates and ones from this team
        else:
            query_condition = Q(team_id=self.team_id) | Q(scope=DashboardTemplate.Scope.GLOBAL)

        qs = DashboardTemplate.objects.filter(query_condition)

        # weighted full-text search
        if isinstance(search, str):
            qs = qs.annotate(
                rank=build_rank({"template_name": "A", "dashboard_description": "C", "tags": "B"}, search),
            )
            qs = qs.filter(rank__gt=0.05)
            qs = qs.order_by("-rank")

        return qs
