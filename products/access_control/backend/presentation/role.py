from functools import cached_property
from typing import TYPE_CHECKING, Optional, cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Prefetch, QuerySet, prefetch_related_objects

from django_otp.plugins.otp_totp.models import TOTPDevice
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from social_django.models import UserSocialAuth

from posthog.api.organization_member import OrganizationMemberSerializer, organization_access_role_memberships_prefetch
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import OrganizationMembership, User
from posthog.models.utils import strict_fetch
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission

from products.access_control.backend.facade import api as access_control_api
from products.access_control.backend.facade.subject_access_control import restricted_visible_membership_ids
from products.access_control.backend.models.role import Role, RoleMembership
from products.access_control.backend.presentation.organization_role_access import (
    organization_role_grants_enabled,
    require_organization_access_management,
)

if TYPE_CHECKING:
    _MixinBase = TeamAndOrgViewSetMixin
else:
    _MixinBase = object


def role_memberships_prefetch(organization_id: UUID) -> Prefetch:
    """Prefetch role members with the relations the member serializer reads, so listing roles
    doesn't fire a per-member social-auth/2FA query.
    """
    return Prefetch(
        "roles",
        queryset=RoleMembership.objects.valid_for_authorization()
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "organization_member",
                queryset=OrganizationMembership.objects.with_effective_level()
                .select_related("user")
                .prefetch_related(organization_access_role_memberships_prefetch(organization_id)),
            ),
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
    organization_access_level = serializers.ChoiceField(
        choices=Role.OrganizationAccessLevel.choices,
        allow_null=True,
        required=False,
        help_text="Additional organization access granted to role members. Null grants no additional access.",
    )

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "created_at",
            "created_by",
            "members",
            "is_default",
            "organization_access_level",
        ]
        read_only_fields = ["id", "created_at", "created_by", "is_default"]

    def validate_name(self, name):
        qs = Role.objects.filter(name__iexact=name, organization=self.context["view"].organization)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("There is already a role with this name.", code="unique")
        return name

    def validate_organization_access_level(self, level: int | None) -> int | None:
        self._grants_enabled = level is not None and organization_role_grants_enabled(
            self.context["request"], self.context["view"].organization
        )
        return level

    def _check_organization_access(self, validated_data: dict, instance: Role | None = None) -> None:
        current_level = instance.organization_access_level if instance else None
        new_level = validated_data.get("organization_access_level", current_level)
        if current_level is not None or new_level is not None:
            organization = self.context["view"].organization
            require_organization_access_management(self.context["request"], organization)
            if new_level is not None and new_level != current_level:
                if not self._grants_enabled:
                    raise serializers.ValidationError(
                        {"organization_access_level": "Organization access grants are not enabled."}
                    )

    def update(self, instance: Role, validated_data: dict) -> Role:
        with transaction.atomic():
            instance = Role.objects.select_for_update(no_key=True).get(
                pk=instance.pk, organization=instance.organization
            )
            self._check_organization_access(validated_data, instance)
            return super().update(instance, validated_data)

    def create(self, validated_data):
        self._check_organization_access(validated_data)
        validated_data["organization"] = self.context["view"].organization
        return super().create(validated_data)

    @extend_schema_field(
        serializers.ListField(child=serializers.DictField(), help_text="Members assigned to this role")
    )
    def get_members(self, role: Role):
        # role.roles are the memberships; reuse RoleViewSet's prefetch instead of re-querying per role.
        prefetch_related_objects([role], role_memberships_prefetch(role.organization_id))
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
    queryset = Role.objects.select_related("created_by")
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission]

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["visible_membership_ids"] = self.visible_membership_ids
        context["visible_user_ids"] = self.visible_user_ids
        return context

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.prefetch_related(role_memberships_prefetch(self.organization.id))
        return strict_fetch(queryset) if self.action == "list" else queryset

    @transaction.atomic
    def perform_destroy(self, instance: Role) -> None:
        instance = Role.objects.select_for_update(no_key=True).get(pk=instance.pk, organization=self.organization)
        if instance.organization_access_level is not None:
            require_organization_access_management(self.request, self.organization)
        if not access_control_api.can_delete_role(role_id=instance.id, user_id=cast(User, self.request.user).id):
            raise PermissionDenied("This role has rules in a project where access control is managed with Terraform.")
        super().perform_destroy(instance)


class RoleMembershipSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    organization_member = OrganizationMemberSerializer(read_only=True)
    role_id = serializers.UUIDField(read_only=True)
    user_uuid = serializers.UUIDField(required=True, write_only=True)

    class Meta:
        model = RoleMembership
        fields = ["id", "role_id", "organization_member", "user", "joined_at", "updated_at", "user_uuid"]
        read_only_fields = ["id", "role_id", "organization_member", "user", "joined_at", "updated_at"]

    @transaction.atomic
    def create(self, validated_data):
        user_uuid = validated_data.pop("user_uuid")

        try:
            role = Role.objects.select_for_update(no_key=True).get(
                id=self.context["role_id"], organization_id=self.context["organization_id"]
            )
        except Role.DoesNotExist:
            raise serializers.ValidationError("Role does not exist.")

        if role.organization_access_level is not None:
            require_organization_access_management(self.context["request"], self.context["view"].organization)

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
    queryset = RoleMembership.objects.valid_for_authorization().select_related("role", "user")
    filter_rewrite_rules = {"organization_id": "role__organization_id"}

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.prefetch_related(
            Prefetch(
                "organization_member",
                queryset=OrganizationMembership.objects.with_effective_level()
                .select_related("user")
                .prefetch_related(
                    organization_access_role_memberships_prefetch(self.organization.id),
                    Prefetch("user__totpdevice_set", queryset=TOTPDevice.objects.filter(confirmed=True)),
                    "user__social_auth",
                    Prefetch("user__webauthn_credentials", queryset=WebauthnCredential.objects.filter(verified=True)),
                ),
            )
        )
        # Legacy rows predating the organization_member FK have it NULL and can't be
        # visibility-checked, so this filter hides them from restricted members rather than leaking.
        if self.visible_membership_ids is not None:
            queryset = queryset.filter(organization_member_id__in=self.visible_membership_ids)
        return queryset

    @transaction.atomic
    def perform_destroy(self, instance: RoleMembership) -> None:
        role = Role.objects.select_for_update(no_key=True).get(pk=instance.role_id, organization=self.organization)
        if role.organization_access_level is not None:
            require_organization_access_management(self.request, self.organization)
        super().perform_destroy(instance)
