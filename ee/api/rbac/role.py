from functools import cached_property
from typing import TYPE_CHECKING, Optional, cast

from django.db import IntegrityError
from django.db.models import Prefetch, QuerySet

from django_otp.plugins.otp_totp.models import TOTPDevice
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import NotFound
from social_django.models import UserSocialAuth

from posthog.api.organization_member import OrganizationMemberSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import OrganizationMembership, User
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission
from posthog.rbac.user_access_control import restricted_visible_membership_ids

from ee.models.rbac.role import Role, RoleMembership

if TYPE_CHECKING:
    _MixinBase = TeamAndOrgViewSetMixin
else:
    _MixinBase = object


def role_memberships_prefetch() -> Prefetch:
    """Prefetch role members with the relations the member serializer reads, so listing roles
    doesn't fire a per-member social-auth/2FA query.
    """
    return Prefetch(
        "roles",
        queryset=RoleMembership.objects.select_related("user", "organization_member__user").prefetch_related(
            Prefetch(
                "organization_member__user__totpdevice_set",
                queryset=TOTPDevice.objects.filter(confirmed=True),
            ),
            Prefetch("organization_member__user__social_auth", queryset=UserSocialAuth.objects.all()),
            Prefetch(
                "organization_member__user__webauthn_credentials",
                queryset=WebauthnCredential.objects.filter(verified=True),
            ),
        ),
    )


class RestrictedMemberVisibilityMixin(_MixinBase):
    """Role endpoints disclose member records, so they scope them the same way the members list
    does when the org restricts member list visibility."""

    @cached_property
    def visible_membership_ids(self) -> Optional[set[str]]:
        return restricted_visible_membership_ids(self.organization, cast(User, self.request.user))

    @cached_property
    def visible_user_ids(self) -> Optional[set[int]]:
        if self.visible_membership_ids is None:
            return None
        return set(
            OrganizationMembership.objects.filter(
                organization=self.organization,
                id__in=self.visible_membership_ids,
            ).values_list("user_id", flat=True)
        )


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
        qs = Role.objects.filter(name__iexact=name, organization=self.context["view"].organization)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("There is already a role with this name.", code="unique")
        return name

    def create(self, validated_data):
        validated_data["organization"] = self.context["view"].organization
        return super().create(validated_data)

    @extend_schema_field(
        serializers.ListField(child=serializers.DictField(), help_text="Members assigned to this role")
    )
    def get_members(self, role: Role):
        # role.roles are the memberships; reuse RoleViewSet's prefetch instead of re-querying per role.
        memberships = list(role.roles.all())
        visible_membership_ids = self.context.get("visible_membership_ids")
        if visible_membership_ids is not None:
            memberships = [
                rm
                for rm in memberships
                if rm.organization_member_id and str(rm.organization_member_id) in visible_membership_ids
            ]
        return RoleMembershipSerializer(memberships, many=True).data

    def to_representation(self, instance: Role):
        data = super().to_representation(instance)
        # Hide the role creator from members who can't see them in the members list.
        visible_user_ids = self.context.get("visible_user_ids")
        if visible_user_ids is not None and instance.created_by_id and instance.created_by_id not in visible_user_ids:
            data["created_by"] = None
        return data

    @extend_schema_field(serializers.BooleanField())
    def get_is_default(self, role: Role):
        """Check if this role is the default role for the organization"""
        view = self.context.get("view")
        if not view:
            return False
        try:
            organization = view.organization
        except NotFound:
            return False
        return organization.default_role_id == role.id


@extend_schema(extensions={"x-product": "platform_features"})
class RoleViewSet(RestrictedMemberVisibilityMixin, TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "organization"
    serializer_class = RoleSerializer
    queryset = Role.objects.prefetch_related(role_memberships_prefetch())
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission]

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["visible_membership_ids"] = self.visible_membership_ids
        context["visible_user_ids"] = self.visible_user_ids
        return context


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
            # nosemgrep: idor-lookup-without-org (organization filter on next line)
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


@extend_schema(extensions={"x-product": "platform_features"})
class RoleMembershipViewSet(
    RestrictedMemberVisibilityMixin,
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "organization"
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission]
    serializer_class = RoleMembershipSerializer
    queryset = RoleMembership.objects.select_related("role")
    filter_rewrite_rules = {"organization_id": "role__organization_id"}

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        # Legacy rows predating the organization_member FK have it NULL and can't be
        # visibility-checked, so this filter hides them from restricted members rather than leaking.
        if self.visible_membership_ids is not None:
            queryset = queryset.filter(organization_member_id__in=self.visible_membership_ids)
        return queryset
