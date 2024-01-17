from typing import cast

from django.db.models import Model, Prefetch
from django.shortcuts import get_object_or_404
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.serializers import raise_errors_on_nested_writes
from social_django.admin import UserSocialAuth

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import INTERNAL_BOT_EMAIL_SUFFIX
from posthog.models import OrganizationMembership
from posthog.models.user import User
from posthog.permissions import OrganizationMemberPermissions, extract_organization


class OrganizationMemberObjectPermissions(BasePermission):
    """Require organization admin level to change object, allowing everyone read AND delete."""

    message = "Your cannot edit other organization members."

    def has_object_permission(self, request: Request, view, membership: OrganizationMembership) -> bool:
        if request.method in SAFE_METHODS:
            return True
        organization = extract_organization(membership)
        requesting_membership: OrganizationMembership = OrganizationMembership.objects.get(
            user_id=cast(User, request.user).id,
            organization=organization,
        )
        try:
            requesting_membership.validate_update(membership)
        except exceptions.ValidationError:
            return False
        return True


class OrganizationMemberSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    is_2fa_enabled = serializers.SerializerMethodField()
    has_social_auth = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationMembership
        fields = [
            "id",
            "user",
            "level",
            "joined_at",
            "updated_at",
            "is_2fa_enabled",
            "has_social_auth",
        ]
        read_only_fields = ["id", "joined_at", "updated_at"]

    def get_is_2fa_enabled(self, instance: OrganizationMembership) -> bool:
        # If we add other forms of 2FA we need to use default_device here instead
        # But not using that here as it increased the number of queries we did by a lot
        return len(instance.user.totpdevice_set.all()) > 0

    def get_has_social_auth(self, instance: OrganizationMembership) -> bool:
        return len(instance.user.social_auth.all()) > 0

    def update(self, updated_membership, validated_data, **kwargs):
        updated_membership = cast(OrganizationMembership, updated_membership)
        raise_errors_on_nested_writes("update", self, validated_data)
        requesting_membership: OrganizationMembership = OrganizationMembership.objects.get(
            organization=updated_membership.organization,
            user=self.context["request"].user,
        )
        for attr, value in validated_data.items():
            if attr == "level":
                requesting_membership.validate_update(updated_membership, value)
            setattr(updated_membership, attr, value)
        updated_membership.save()
        return updated_membership


class OrganizationMemberViewSet(
    StructuredViewSetMixin,
    mixins.DestroyModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = OrganizationMemberSerializer
    permission_classes = [
        IsAuthenticated,
        OrganizationMemberPermissions,
        OrganizationMemberObjectPermissions,
    ]
    queryset = (
        OrganizationMembership.objects.order_by("user__first_name", "-joined_at")
        .exclude(user__email__endswith=INTERNAL_BOT_EMAIL_SUFFIX)
        .filter(
            user__is_active=True,
        )
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "user__totpdevice_set",
                queryset=TOTPDevice.objects.filter(name="default"),
            ),
            Prefetch("user__social_auth", queryset=UserSocialAuth.objects.all()),
        )
    )
    lookup_field = "user__uuid"

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@me":
            return queryset.get(user=self.request.user)
        filter_kwargs = {self.lookup_field: lookup_value}
        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def perform_destroy(self, instance: Model):
        instance = cast(OrganizationMembership, instance)
        instance.user.leave(organization=instance.organization)
