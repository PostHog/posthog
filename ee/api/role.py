from typing import cast

from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated

from ee.models.role import Role, RoleMembership
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import OrganizationMembership
from posthog.models.user import User
from posthog.permissions import extract_organization

DEFAULT_ROLE_NAME = "Write"


class RolePermissions(BasePermission):
    """
    Requires organization admin level to change object, allows everyone read
    """

    message = "You need to have admin level or higher."

    def has_permission(self, request, view):
        organization = extract_organization(request.user)

        requesting_membership: OrganizationMembership = OrganizationMembership.objects.get(
            user_id=cast(User, request.user).id,
            organization=organization,
        )

        if request.method in SAFE_METHODS or requesting_membership.level >= OrganizationMembership.Level.ADMIN:
            return True
        return False


class RoleSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Role
        fields = ["id", "name", "created_at", "created_by"]
        read_only_fields = ["id", "created_at", "created_by"]

    def validate_name(self, name):
        if Role.objects.filter(name__iexact=name).exists():
            raise serializers.ValidationError("There is already a role with this name.", code="unique")
        return name

    def create(self, validated_data):
        validated_data["organization"] = self.context["request"].user.organization
        return super().create(validated_data)


class RoleViewSet(
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [
        IsAuthenticated,
        RolePermissions,
    ]
    serializer_class = RoleSerializer
    queryset = Role.objects.all()


class RoleMembershipSerializer(serializers.ModelSerializer):
    # user = UserBasicSerializer(read_only=True)

    class Meta:
        model = RoleMembership
        fields = ["role", "user", "joined_at", "updated_at"]


class RoleMembershipViewSet(
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [
        IsAuthenticated,
        RolePermissions,
    ]
    serializer_class = RoleMembershipSerializer
    queryset = RoleMembership.objects.all()
