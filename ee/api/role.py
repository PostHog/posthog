from typing import List, cast

from django.db import IntegrityError
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated

from ee.models.feature_flag_role_access import FeatureFlagRoleAccess
from ee.models.organization_resource_access import OrganizationResourceAccess
from ee.models.role import Role, RoleMembership
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import OrganizationMembership
from posthog.models.feature_flag import FeatureFlag
from posthog.models.user import User
from posthog.permissions import OrganizationMemberPermissions


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
    associated_flags = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "feature_flags_access_level",
            "created_at",
            "created_by",
            "members",
            "associated_flags",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

    def validate_name(self, name):
        if Role.objects.filter(name__iexact=name, organization=self.context["request"].user.organization).exists():
            raise serializers.ValidationError("There is already a role with this name.", code="unique")
        return name

    def create(self, validated_data):
        organization = self.context["request"].user.organization
        validated_data["organization"] = organization
        try:
            default_flags_org_setting = OrganizationResourceAccess.objects.get(
                organization=organization,
                resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            ).access_level
        except OrganizationResourceAccess.DoesNotExist:
            default_flags_org_setting = OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT
        validated_data["feature_flags_access_level"] = default_flags_org_setting
        return super().create(validated_data)

    def get_members(self, role: Role):
        members = RoleMembership.objects.filter(role=role)
        return RoleMembershipSerializer(members, many=True).data

    def get_associated_flags(self, role: Role):
        associated_flags: List[dict] = []

        role_access_objects = FeatureFlagRoleAccess.objects.filter(role=role).values_list("feature_flag_id")
        flags = FeatureFlag.objects.filter(id__in=role_access_objects)
        for flag in flags:
            associated_flags.append({"id": flag.id, "key": flag.key})
        return associated_flags


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

    def get_queryset(self):
        filters = self.request.GET.dict()
        return super().get_queryset().filter(**filters)


class RoleMembershipSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    role_id = serializers.UUIDField(read_only=True)
    user_uuid = serializers.UUIDField(required=True, write_only=True)

    class Meta:
        model = RoleMembership
        fields = ["id", "role_id", "user", "joined_at", "updated_at", "user_uuid"]

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
