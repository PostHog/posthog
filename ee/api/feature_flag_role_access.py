from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission

from ee.api.rbac.role import RoleSerializer
from ee.models.feature_flag_role_access import FeatureFlagRoleAccess
from ee.models.rbac.organization_resource_access import OrganizationResourceAccess
from ee.models.rbac.role import Role
from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import FeatureFlag
from posthog.models.organization import OrganizationMembership


class FeatureFlagRoleAccessPermissions(BasePermission):
    message = "You can't edit roles for this feature flag."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if (
            request.user.organization_memberships.get(organization=request.user.organization).level
            >= OrganizationMembership.Level.ADMIN
        ):
            return True
        try:
            resource_access = OrganizationResourceAccess.objects.get(
                resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
                organization=request.user.organization,
            )
            if resource_access.access_level == OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT:
                return True
        except (
            OrganizationResourceAccess.DoesNotExist
        ):  # no organization resource access for this means full default edit access
            return True
        try:
            feature_flag: FeatureFlag = FeatureFlag.objects.get(id=view.parents_query_dict["feature_flag_id"])
            if (
                hasattr(feature_flag, "created_by")
                and feature_flag.created_by
                and feature_flag.created_by.uuid == request.user.uuid
            ):
                return True
        except FeatureFlag.DoesNotExist:
            raise exceptions.NotFound("Feature flag not found.")

        has_role_membership_with_access = request.user.role_memberships.filter(
            role__feature_flags_access_level=OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT
        ).exists()
        return has_role_membership_with_access


class FeatureFlagRoleAccessSerializer(serializers.ModelSerializer):
    feature_flag = FeatureFlagSerializer(read_only=True)
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(write_only=True, source="role", queryset=Role.objects.all())

    class Meta:
        model = FeatureFlagRoleAccess
        fields = ["id", "feature_flag", "role", "role_id", "added_at", "updated_at"]
        read_only_fields = ["id", "added_at", "updated_at"]

    def create(self, validated_data):
        validated_data["feature_flag_id"] = self.context["feature_flag_id"]
        return super().create(validated_data)


class FeatureFlagRoleAccessViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "feature_flag"
    permission_classes = [FeatureFlagRoleAccessPermissions]
    serializer_class = FeatureFlagRoleAccessSerializer
    queryset = FeatureFlagRoleAccess.objects.select_related("feature_flag")
    filter_rewrite_rules = {"project_id": "feature_flag__team__project_id"}

    def safely_get_queryset(self, queryset):
        filters = self.request.GET.dict()
        return queryset.filter(**filters)
