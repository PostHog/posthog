from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated

from ee.models.feature_flag_role_access import FeatureFlagRoleAccess
from ee.models.organization_resource_access import OrganizationResourceAccess
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import FeatureFlag


class FeatureFlagRoleAccessPermissions(BasePermission):
    message = "You can't edit roles to this feature flag."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if OrganizationResourceAccess.objects.filter(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            access_level=OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT,
        ).exists():
            return True
        try:
            feature_flag: FeatureFlag = FeatureFlag.objects.get(id=request.data["feature_flag"])
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
    class Meta:
        model = FeatureFlagRoleAccess
        fields = ["id", "feature_flag", "role", "added_at", "updated_at"]
        read_only_fields = ["id", "added_at", "updated_at"]


class FeatureFlagRoleAccessViewSet(
    StructuredViewSetMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, FeatureFlagRoleAccessPermissions]
    serializer_class = FeatureFlagRoleAccessSerializer
