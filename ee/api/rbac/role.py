from typing import cast

from django.db import IntegrityError

from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission

from posthog.api.organization_member import OrganizationMemberSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import OrganizationMembership
from posthog.models.user import User
from posthog.permissions import TimeSensitiveActionPermission

from ee.models.rbac.role import Role, RoleMembership


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
    members = serializers.SerializerMethodField()
    is_default = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "created_at",
            "created_by",
            "members",
            "is_default",
        ]
        read_only_fields = ["id", "created_at", "created_by", "is_default"]

    def validate_name(self, name):
        if Role.objects.filter(name__iexact=name, organization=self.context["request"].user.organization).exists():
            raise serializers.ValidationError("There is already a role with this name.", code="unique")
        return name

    def create(self, validated_data):
        organization = self.context["request"].user.organization
        validated_data["organization"] = organization
        return super().create(validated_data)

    def get_members(self, role: Role):
        members = RoleMembership.objects.filter(role=role)
        return RoleMembershipSerializer(members, many=True).data

    def get_is_default(self, role: Role):
        """Check if this role is the default role for the organization"""
        request = self.context.get("request")
        if not request or not hasattr(request, "user") or not request.user.is_authenticated:
            return False
        organization = getattr(request.user, "organization", None)
        if not organization:
            return False
        return organization.default_role_id == role.id


class RoleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "organization"
    serializer_class = RoleSerializer
    queryset = Role.objects.all()
    permission_classes = [RolePermissions, TimeSensitiveActionPermission]

    def safely_get_queryset(self, queryset):
        return queryset.filter(**self.request.GET.dict())


class RoleMembershipSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    organization_member = OrganizationMemberSerializer(read_only=True)
    role_id = serializers.UUIDField(read_only=True)
    user_uuid = serializers.UUIDField(required=True, write_only=True)

    class Meta:
        model = RoleMembership
        fields = ["id", "role_id", "organization_member", "user", "joined_at", "updated_at", "user_uuid"]
        read_only_fields = ["id", "role_id", "organization_member", "user", "joined_at", "updated_at"]

    def create(self, validated_data):
        user_uuid = validated_data.pop("user_uuid")

        try:
            role = Role.objects.get(id=self.context["role_id"])
        except Role.DoesNotExist:
            raise serializers.ValidationError("Role does not exist.")

        if role.organization_id != self.context["organization_id"]:
            raise serializers.ValidationError("Role does not exist.")

        try:
            validated_data["organization_member"] = OrganizationMembership.objects.select_related("user").get(
                organization_id=role.organization_id, user__uuid=user_uuid, user__is_active=True
            )

            validated_data["user"] = validated_data["organization_member"].user
        except OrganizationMembership.DoesNotExist:
            raise serializers.ValidationError("User does not exist.")
        validated_data["role_id"] = self.context["role_id"]
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError("User is already part of the role.")


class RoleMembershipViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "organization"
    permission_classes = [RolePermissions, TimeSensitiveActionPermission]
    serializer_class = RoleMembershipSerializer
    queryset = RoleMembership.objects.select_related("role")
    filter_rewrite_rules = {"organization_id": "role__organization_id"}
