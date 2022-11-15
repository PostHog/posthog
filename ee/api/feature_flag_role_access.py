from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated

from ee.models.feature_flag_role_access import FeatureFlagRoleAccess
from ee.models.role import Role
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import FeatureFlag, Organization
from posthog.models.user import User
import pdb


class FeatureFlagRoleAccessPermissions(BasePermission):
    """
    Requires role
    """

    message = "You can't edit roles to this feature flag."

    def has_permission(self, request, view):
        return True
        if request.method in SAFE_METHODS:
            return True
        try:
            feature_flag: FeatureFlag = FeatureFlagRoleAccess.objects.get(id=view.parents_query_dict["feature_flag_id"])
            # dashboard: Dashboard = Dashboard.objects.get(id=view.parents_query_dict["dashboard_id"])
        except FeatureFlag.DoesNotExist:
            raise exceptions.NotFound("Feature flag not found.")
        # return dashboard.can_user_edit(cast(User, request.user).id)

        # organization = request.user.organization

        # requesting_membership: OrganizationMembership = OrganizationMembership.objects.get(
        #     user_id=cast(User, request.user).id,
        #     organization=organization,
        # )

        # if request.method in SAFE_METHODS or requesting_membership.level >= OrganizationMembership.Level.ADMIN:
        #     return True
        # return False


class FeatureFlagRoleAccessSerializer(serializers.ModelSerializer):
    # feature_flag_ids = serializers.ListField(child=serializers.IntegerField(), required=True, write_only=True)

    class Meta:
        model = FeatureFlagRoleAccess
        fields = ["feature_flag", "role", "added_at", "updated_at"]
        read_only_fields = ["added_at", "updated_at"]

    def create(self, validated_data):
        # role: Role = self.context["role"]
        # feature_flag_id = validated_data.pop("feature_flag_id")
        # role: Role =
        # try:
        #     validated_data["feature_flag"] = FeatureFlag.objects.get(id=feature_flag_id)
        # except FeatureFlag.DoesNotExist:
        #     raise serializers.ValidationError("Feature flag does not exist.")

        # org allows for creation
        pdb.set_trace()
        org = Organization.objects.get(id=self.context["organization_id"])
        feature_flag = FeatureFlag.objects.get(id=validated_data["feature_flag_id"])
        if (
            org.feature_flags_access_level >= Organization.FeatureFlagsAccessLevel.CAN_ALWAYS_EDIT
            or feature_flag.created_by == self
        ):
            return super().create(validated_data)
        # role_memberships = self.user.role_memberships.all()

        # feature_flag_ids = validated_data.pop("feature_flag_ids")
        # role = Role.objects.get(id=self.context["role_id"])
        # org = Organization.objects.get(id=self.context["organization_id"])
        # org_teams = org.teams.all()
        # feature_flags = FeatureFlag.objects.filter(team__in=org_teams, id__in=feature_flag_ids)
        # access_roles = (FeatureFlagRoleAccess(feature_flag=feature_flag, role=role) for feature_flag in feature_flags)
        # return access_roles


class FeatureFlagRoleAccessViewSet(
    StructuredViewSetMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, FeatureFlagRoleAccessPermissions]
    serializer_class = FeatureFlagRoleAccessSerializer
    queryset = FeatureFlagRoleAccess.objects.select_related("role")
