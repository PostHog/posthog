from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated

from ee.api.role import RoleSerializer
from ee.models.feature_flag_role_access import FeatureFlagRoleAccess
from ee.models.organization_resource_access import OrganizationResourceAccess
from ee.models.role import Role
from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import FeatureFlag


class FeatureFlagRoleAccessPermissions(BasePermission):
    message = "You can't edit roles to this feature flag."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        try:
            resource_access = OrganizationResourceAccess.objects.get(
                resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS
            )
            if resource_access.access_level == OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT:
                return True
        except OrganizationResourceAccess.DoesNotExist:  # no organization resource access for this means full default edit access
            return True
        try:
            feature_flag: FeatureFlag = FeatureFlag.objects.get(id=request.data["feature_flag_id"])
            if feature_flag.created_by.uuid == request.user.uuid:
                return True
        except FeatureFlag.DoesNotExist:
            raise exceptions.NotFound("Feature flag not found.")

        has_role_membership_with_access = (
            request.user.role_memberships.all()
            .filter(role__feature_flags_access_level=OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT)
            .exists()
        )
        if has_role_membership_with_access:
            return True

        return False


class FeatureFlagRoleAccessSerializer(serializers.ModelSerializer):
    feature_flag = FeatureFlagSerializer(read_only=True)
    feature_flag_id = serializers.PrimaryKeyRelatedField(
        write_only=True, source="feature_flag", queryset=FeatureFlag.objects.all()
    )
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(write_only=True, source="role", queryset=Role.objects.all())

    class Meta:
        model = FeatureFlagRoleAccess
        fields = ["id", "feature_flag", "feature_flag_id", "role", "role_id", "added_at", "updated_at"]
        read_only_fields = ["id", "added_at", "updated_at"]

    def create(self, validated_data):
        validated_data["organization"] = self.context["request"].user.organization
        return super().create(validated_data)


class FeatureFlagRoleAccessViewSet(
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, FeatureFlagRoleAccessPermissions]
    serializer_class = FeatureFlagRoleAccessSerializer
    queryset = FeatureFlagRoleAccess.objects.select_related("role").select_related("feature_flag").all()

    def get_queryset(self):
        filters = self.request.GET.dict()
        return super().get_queryset().filter(**filters)
