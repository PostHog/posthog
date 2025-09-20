from typing import Any, cast

from django.db import IntegrityError

from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import Dashboard, User
from posthog.user_permissions import UserPermissions, UserPermissionsSerializerMixin

from ee.models.dashboard_privilege import DashboardPrivilege


class CanEditDashboardCollaborator(BasePermission):
    message = "You don't have edit permissions for this dashboard."

    def has_permission(self, request: Request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True
        try:
            dashboard: Dashboard = Dashboard.objects.get(id=view.parents_query_dict["dashboard_id"])
        except Dashboard.DoesNotExist:
            raise exceptions.NotFound("Dashboard not found.")

        return view.user_permissions.dashboard(dashboard).can_edit


class DashboardCollaboratorSerializer(serializers.ModelSerializer, UserPermissionsSerializerMixin):
    user = UserBasicSerializer(read_only=True)
    dashboard_id = serializers.IntegerField(read_only=True)

    user_uuid = serializers.UUIDField(required=True, write_only=True)

    class Meta:
        model = DashboardPrivilege
        fields = [
            "id",
            "dashboard_id",
            "user",
            "level",
            "added_at",
            "updated_at",
            "user_uuid",  # write_only (see above)
        ]
        read_only_fields = ["id", "dashboard_id", "user"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        dashboard: Dashboard = self.context["dashboard"]
        dashboard_permissions = self.user_permissions.dashboard(dashboard)
        if dashboard_permissions.effective_restriction_level <= Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT:
            raise exceptions.ValidationError("Cannot add collaborators to a dashboard on the lowest restriction level.")
        attrs = super().validate(attrs)
        level = attrs.get("level")
        if level is not None and level != Dashboard.PrivilegeLevel.CAN_EDIT:
            raise serializers.ValidationError("Only edit access can be explicitly specified currently.")
        return attrs

    def create(self, validated_data):
        dashboard: Dashboard = self.context["dashboard"]
        user_uuid = validated_data.pop("user_uuid")
        try:
            validated_data["user"] = User.objects.filter(is_active=True).get(uuid=user_uuid)
        except User.DoesNotExist:
            raise serializers.ValidationError("User does not exist.")

        modified_user_permissions = UserPermissions(
            user=validated_data["user"],
            team=self.context["view"].team,
        )
        if modified_user_permissions.current_team.effective_membership_level is None:
            raise exceptions.ValidationError("Cannot add collaborators that have no access to the project.")
        if modified_user_permissions.dashboard(dashboard).can_restrict:
            raise exceptions.ValidationError(
                "Cannot add collaborators that already have inherent access (the dashboard owner or a project admins)."
            )
        validated_data["dashboard_id"] = self.context["dashboard_id"]
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError("User already is a collaborator.")


class DashboardCollaboratorViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "dashboard"
    permission_classes = [CanEditDashboardCollaborator]
    pagination_class = None
    queryset = DashboardPrivilege.objects.select_related("dashboard", "dashboard__team").filter(user__is_active=True)
    lookup_field = "user__uuid"
    serializer_class = DashboardCollaboratorSerializer
    filter_rewrite_rules = {"project_id": "dashboard__team__project_id"}

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        try:
            context["dashboard"] = Dashboard.objects.get(id=context["dashboard_id"])
        except Dashboard.DoesNotExist:
            raise exceptions.NotFound("Dashboard not found.")
        return context

    def perform_destroy(self, instance) -> None:
        dashboard = cast(Dashboard, instance.dashboard)
        if (
            self.user_permissions.dashboard(dashboard).effective_restriction_level
            <= Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        ):
            raise exceptions.ValidationError(
                "Cannot remove collaborators from a dashboard on the lowest restriction level."
            )
        return super().perform_destroy(instance)
