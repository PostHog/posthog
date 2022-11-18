from typing import Dict, Literal, Type

from django.db.models import Q
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import DashboardTemplate, OrganizationMembership, Team, User
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.utils import str_to_bool


def _check_permissions(scope: str, team: Team, user: User, action: Literal["edit", "create"]) -> None:
    if team != user.team:
        raise PermissionDenied(f"You can only {action} templates for your own team")

    is_staff = user.is_staff
    if not is_staff and scope == DashboardTemplate.Scope.GLOBAL.value:
        raise PermissionDenied(f"You must be a staff user to {action} a global template")

    membership_level = team.get_effective_membership_level(user.id)
    if (
        membership_level == OrganizationMembership.Level.MEMBER.value
        and scope == DashboardTemplate.Scope.ORGANIZATION.value
    ):
        raise PermissionDenied(f"You must be an organization admin or higher to {action} an organization template")


class DashboardTemplateBasicSerializer(serializers.Serializer):
    id: serializers.UUIDField = serializers.UUIDField(read_only=True)
    scope: serializers.CharField = serializers.CharField(max_length=24)
    template_name: serializers.CharField = serializers.CharField(max_length=400, required=False)
    deleted: serializers.BooleanField = serializers.BooleanField(write_only=True, default=False, required=False)

    def validate(self, data: Dict) -> Dict:
        if "template_name" in data:
            template_name = data.get("template_name", None)
            if not template_name or not isinstance(template_name, str) or str.isspace(template_name):
                raise serializers.ValidationError("Must provide a template name")

        if "deleted" in data:
            deleted = data.get("deleted", None)
            if not isinstance(str_to_bool(deleted), bool):
                raise serializers.ValidationError("Must provide a valid deleted value")

        return data

    def update(self, instance: DashboardTemplate, validated_data: dict) -> DashboardTemplate:
        team = Team.objects.get(id=self.context["team_id"])
        user = self.context["request"].user

        _check_permissions(instance.scope, team, user, "edit")

        updated_fields = []

        if "template_name" in validated_data:
            instance.template_name = validated_data["template_name"]
            updated_fields.append("template_name")

        if "deleted" in validated_data:
            instance.deleted = validated_data["deleted"]
            updated_fields.append("deleted")

        if updated_fields:
            instance.save(update_fields=updated_fields)

        return instance


class DashboardTemplateSerializer(serializers.Serializer):
    id: serializers.UUIDField = serializers.UUIDField(read_only=True)
    template_name: serializers.CharField = serializers.CharField(max_length=400)
    source_dashboard: serializers.IntegerField = serializers.IntegerField(allow_null=True)
    dashboard_description: serializers.CharField = serializers.CharField(max_length=400, allow_blank=True)
    dashboard_filters: serializers.JSONField = serializers.JSONField(allow_null=True, required=False)
    tiles: serializers.JSONField = serializers.JSONField(default=dict)
    tags: serializers.ListField = serializers.ListField(child=serializers.CharField(), allow_null=True)
    scope: serializers.CharField = serializers.CharField(max_length=24)

    def validate(self, data: Dict) -> Dict:
        team = Team.objects.get(id=self.context["team_id"])
        user = self.context["request"].user

        scope = data.get("scope")
        if not scope:
            raise serializers.ValidationError("Must provide a scope")
        _check_permissions(scope, team, user, "create")

        template_name = data.get("template_name", None)
        if not template_name or not isinstance(template_name, str) or str.isspace(template_name):
            raise serializers.ValidationError("Must provide a template name")

        try:
            DashboardTemplate.objects.filter(
                template_name=template_name, scope=scope, team=team, organization=user.organization
            ).get()
        except DashboardTemplate.DoesNotExist:
            pass
        else:
            raise serializers.ValidationError("Template name must be unique within a scope, team, and organization")

        if not data.get("source_dashboard") and scope != DashboardTemplate.Scope.GLOBAL.value:
            raise serializers.ValidationError("Must provide the id of the source dashboard")

        if not data.get("tiles") or not isinstance(data["tiles"], list):
            raise serializers.ValidationError("Must provide at least one tile")

        for tile in data["tiles"]:
            if "layouts" not in tile or not isinstance(tile["layouts"], dict):
                raise serializers.ValidationError("Must provide a tile layouts")

            if not tile.get("type"):
                raise serializers.ValidationError("Must provide a tile type")

            if tile.get("type") == "INSIGHT":
                if not tile.get("filters"):
                    raise serializers.ValidationError("Must provide insight filters")
                if not tile.get("name"):
                    raise serializers.ValidationError("Must provide insight name")
            elif tile.get("type") == "TEXT":
                if not tile.get("body"):
                    raise serializers.ValidationError("Must provide text body")
            else:
                raise serializers.ValidationError("Must provide a valid tile type")

        return data

    def create(self, validated_data: Dict) -> DashboardTemplate:
        team = Team.objects.get(id=self.context["team_id"])
        organization = team.organization
        return DashboardTemplate.objects.create(**validated_data, team=team, organization=organization)


class DashboardTemplatesViewSet(
    StructuredViewSetMixin,
    viewsets.GenericViewSet,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    ForbidDestroyModel,
):
    queryset = DashboardTemplate.objects.all()
    serializer_class = DashboardTemplateSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def get_serializer_class(self) -> Type[serializers.BaseSerializer]:
        if str_to_bool(self.request.query_params.get("basic", "0")):
            return DashboardTemplateBasicSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        organization_scoped_templates = Q(organization=self.organization) & Q(scope="organization")

        return (
            DashboardTemplate.objects.exclude(deleted=True)
            .filter(Q(team=self.team) | organization_scoped_templates | Q(scope="global"))
            .distinct()
            .all()
        )

    def retrieve(self, request, *args, **kwargs) -> Response:
        user = request.user
        team = user.team
        organization = team.organization

        try:
            instance = DashboardTemplate.objects.exclude(deleted=True).get(id=kwargs["pk"])
        except DashboardTemplate.DoesNotExist:
            raise NotFound(detail="Dashboard template not found")

        if (instance.scope == "organization" and instance.organization != organization) or (
            instance.scope == "project" and instance.team != team
        ):
            raise PermissionDenied(detail="You cannot access this template")

        serializer = self.get_serializer(instance)
        return Response(serializer.data)
