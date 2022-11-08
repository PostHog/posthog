from typing import cast

from django.db import IntegrityError
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated

from ee.models.role import Role, RoleMembership
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import OrganizationMembership
from posthog.models.user import User
from posthog.permissions import OrganizationMemberPermissions

DEFAULT_ROLE_NAME = "Write"


class RolePermissions(BasePermission):
    """
    Requires organization admin level to change object, allows everyone read
    """

    message = "You need to have admin level or higher."

    def has_permission(self, request, view):
        organization = request.user.organization

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
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [
        IsAuthenticated,
        OrganizationMemberPermissions,
        RolePermissions,
    ]
    serializer_class = RoleSerializer
    queryset = Role.objects.all()


class RoleMembershipSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    role_id = serializers.UUIDField(read_only=True)

    user_uuid = serializers.UUIDField(required=True, write_only=True)

    class Meta:
        model = RoleMembership
        fields = ["role_id", "user", "joined_at", "updated_at", "user_uuid"]
        read_only_fields = ["id", "role_id", "user"]

    def create(self, validated_data):
        user_uuid = validated_data.pop("user_uuid")
        try:
            validated_data["user"] = User.objects.filter(is_active=True).get(uuid=user_uuid)
        except User.DoesNotExist:
            raise serializers.ValidationError("User does not exist.")
        validated_data["role_id"] = self.context["role_id"]
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError("User is already part of the role.")


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
    queryset = RoleMembership.objects.select_related("role")
    filter_rewrite_rules = {"organization_id": "role__organization_id"}
