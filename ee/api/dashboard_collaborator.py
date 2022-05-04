from typing import Any, Dict, cast

from django.db import IntegrityError
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request

from ee.models.dashboard_privilege import DashboardPrivilege
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import Dashboard, Team, User
from posthog.permissions import TeamMemberAccessPermission


class CanEditDashboardCollaborator(BasePermission):
    message = "You don't have edit permissions for this dashboard."

    def has_permission(self, request: Request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True
        try:
            dashboard: Dashboard = Dashboard.objects.get(id=view.parents_query_dict["dashboard_id"])
        except Dashboard.DoesNotExist:
            raise exceptions.NotFound("Dashboard not found.")
        return dashboard.can_user_edit(cast(User, request.user).id)


class DashboardCollaboratorSerializer(serializers.ModelSerializer):
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
        read_only_fields = ["id", "dashboard_id", "user", "user"]

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        dashboard: Dashboard = self.context["dashboard"]
        if dashboard.effective_restriction_level <= Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT:
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
        if cast(Team, dashboard.team).get_effective_membership_level(validated_data["user"].id) is None:
            raise exceptions.ValidationError("Cannot add collaborators that have no access to the project.")
        if dashboard.can_user_restrict(validated_data["user"].id):
            raise exceptions.ValidationError(
                "Cannot add collaborators that already have inherent access (the dashboard owner or a project admins)."
            )
        validated_data["dashboard_id"] = self.context["dashboard_id"]
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError("User already is a collaborator.")


class DashboardCollaboratorViewSet(
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, TeamMemberAccessPermission, CanEditDashboardCollaborator]
    pagination_class = None
    queryset = DashboardPrivilege.objects.select_related("dashboard").filter(user__is_active=True)
    lookup_field = "user__uuid"
    serializer_class = DashboardCollaboratorSerializer
    filter_rewrite_rules = {"team_id": "dashboard__team_id"}
    include_in_docs = False

    def get_serializer_context(self) -> Dict[str, Any]:
        context = super().get_serializer_context()
        try:
            context["dashboard"] = Dashboard.objects.get(id=context["dashboard_id"])
        except Dashboard.DoesNotExist:
            raise exceptions.NotFound("Dashboard not found.")
        return context

    def perform_destroy(self, instance) -> None:
        dashboard = cast(Dashboard, instance.dashboard)
        if dashboard.effective_restriction_level <= Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT:
            raise exceptions.ValidationError(
                "Cannot remove collaborators from a dashboard on the lowest restriction level."
            )
        return super().perform_destroy(instance)
