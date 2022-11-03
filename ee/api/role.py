from ee.models.role import Role, RoleMembership
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework import exceptions, mixins, serializers, viewsets
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.permissions import OrganizationAdminWritePermissions, OrganizationMemberPermissions, extract_organization


class RoleSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Role
        fields = ["id", "name", "created_at", "created_by"]
        read_only_fields = ["id", "created_at", "created_by"]


class RoleViewSet(
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [
        IsAuthenticated,
        # OrganizationMemberPermissions,
        # OrganizationAdminWritePermissions
    ]
    serializer_class = RoleSerializer
    queryset = Role.objects.all()


class RoleMembershipSerializer(serializers.ModelSerializer):
    # user = UserBasicSerializer(read_only=True)

    class Meta:
        model = RoleMembership
        fields = ["role", "user", "joined_at", "updated_at"]

    def validate_name(self, name):
        if Role.objects.filter(name=name).exists():
            raise serializers.ValidationError("There is already a role with this name.", code="unique")
        return name


class RoleMembershipViewSet(
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [
        IsAuthenticated,
        # OrganizationMemberPermissions,
        # OrganizationAdminWritePermissions
    ]
    serializer_class = RoleMembershipSerializer
    queryset = RoleMembership.objects.all()
