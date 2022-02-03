from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from ee.models.dashboard_privilege import DashboardPrivilege
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.dashboard import Dashboard
from posthog.permissions import TeamMemberAccessPermission


class DashboardCollaboratorSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer()
    effective_level = serializers.SerializerMethodField()

    user_uuid = serializers.UUIDField(required=True, write_only=True)

    class Meta:
        model = DashboardPrivilege
        fields = [
            "id",
            "dashboard",
            "user",
            "level",
            "added_at",
            "updated_at",
            "user_uuid",  # write_only (see above)
            "effective_level",  # read_only (calculated)
        ]
        read_only_fields = ["id", "parent_membership_id", "joined_at", "updated_at", "user", "effective_level"]

    def get_effective_level(self, dashboard_privilege: DashboardPrivilege) -> Dashboard.PrivilegeLevel:
        return dashboard_privilege.dashboard.get_effective_privilege_level(dashboard_privilege.user_id)


class DashboardCollaboratorViewSet(
    StructuredViewSetMixin, viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, TeamMemberAccessPermission]
    pagination_class = None
    queryset = DashboardPrivilege.objects.all()
    lookup_field = "user__uuid"
    serializer_class = DashboardCollaboratorSerializer
    filter_rewrite_rules = {"team_id": "dashboard__team_id"}
    include_in_docs = False
