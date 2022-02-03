from typing import Any, Dict, cast

from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, mixins, request, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated

from ee.models.dashboard_privilege import DashboardPrivilege
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.dashboard import Dashboard
from posthog.models.user import User
from posthog.permissions import TeamMemberAccessPermission


class CanEditDashboard(BasePermission):
    message = "This dashboard can only be edited by its owner, team members invited to editing this dashboard, and project admins."

    def has_permission(self, request: request.Request, view: "DashboardCollaboratorViewSet") -> bool:
        if request.method in SAFE_METHODS:
            return True
        dashboard: Dashboard = get_object_or_404(Dashboard.objects.filter(id=view.parents_query_dict["dashboard_id"]))
        return dashboard.can_user_edit(cast(User, request.user).id)


class DashboardCollaboratorSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    dashboard_id = serializers.IntegerField(read_only=True)
    effective_level = serializers.SerializerMethodField()

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
            "effective_level",  # read_only (calculated)
        ]
        read_only_fields = ["id", "dashboard_id", "user", "user", "effective_level"]

    def get_effective_level(self, dashboard_privilege: DashboardPrivilege) -> Dashboard.PrivilegeLevel:
        return dashboard_privilege.dashboard.get_effective_privilege_level(dashboard_privilege.user_id)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        dashboard = Dashboard.objects.get(id=self.context["dashboard_id"])
        if dashboard.restriction_level <= Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT:
            raise exceptions.ValidationError("Cannot add collaborators to a dashboard on the lowest restriction level.")
        attrs = super().validate(attrs)
        level = attrs.get("level")
        if level is not None and level <= Dashboard.PrivilegeLevel.CAN_VIEW:
            raise serializers.ValidationError(
                "View access is the base privilege level for a dashboard, so it can't be set explicitly."
            )
        return attrs

    def create(self, validated_data):
        user_uuid = validated_data.pop("user_uuid")
        try:
            validated_data["user"] = User.objects.get(uuid=user_uuid)
        except User.DoesNotExist:
            raise serializers.ValidationError("User does not exist.")
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
    permission_classes = [IsAuthenticated, TeamMemberAccessPermission, CanEditDashboard]
    pagination_class = None
    queryset = DashboardPrivilege.objects.all()
    lookup_field = "user__uuid"
    serializer_class = DashboardCollaboratorSerializer
    filter_rewrite_rules = {"team_id": "dashboard__team_id"}
    include_in_docs = False

    def get_queryset(self):
        dashboard: Dashboard = get_object_or_404(Dashboard.objects.filter(id=self.parents_query_dict["dashboard_id"]))
        return super().get_queryset().exclude(user_id=dashboard.created_by_id)
