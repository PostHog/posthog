from typing import cast

from django.db.models import F, Model, Prefetch, QuerySet
from django.shortcuts import get_object_or_404

from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import raise_errors_on_nested_writes
from social_django.admin import UserSocialAuth

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import INTERNAL_BOT_EMAIL_SUFFIX
from posthog.event_usage import groups
from posthog.models import OrganizationMembership
from posthog.models.user import User
from posthog.permissions import TimeSensitiveActionPermission, extract_organization
from posthog.utils import posthoganalytics


class OrganizationMemberObjectPermissions(BasePermission):
    """Require organization admin level to change object, allowing everyone read AND delete."""

    message = "Your cannot edit other organization members."

    def has_object_permission(self, request: Request, view, membership: OrganizationMembership) -> bool:
        if request.method in SAFE_METHODS:
            return True
        organization = extract_organization(membership, view)
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
    last_login = serializers.DateTimeField(read_only=True)

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
            "last_login",
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
        level_changed = False
        for attr, value in validated_data.items():
            if attr == "level":
                requesting_membership.validate_update(updated_membership, value)
                level_changed = True
            setattr(updated_membership, attr, value)
        updated_membership.save()
        if level_changed:
            self.context["request"].user.update_billing_organization_users(updated_membership.organization)
        return updated_membership


class OrganizationMemberViewSet(
    TeamAndOrgViewSetMixin,
    mixins.DestroyModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "organization_member"
    serializer_class = OrganizationMemberSerializer
    permission_classes = [OrganizationMemberObjectPermissions, TimeSensitiveActionPermission]
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
        .annotate(last_login=F("user__last_login"))
    )
    lookup_field = "user__uuid"

    def safely_get_object(self, queryset):
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@me":
            return queryset.get(user=self.request.user)
        filter_kwargs = {self.lookup_field: lookup_value}
        return get_object_or_404(queryset, **filter_kwargs)

    def safely_get_queryset(self, queryset) -> QuerySet:
        if self.action == "list":
            params = self.request.GET.dict()

            if "email" in params:
                queryset = queryset.filter(user__email=params["email"])

            if "updated_after" in params:
                queryset = queryset.filter(updated_at__gt=params["updated_after"])

            order = self.request.GET.get("order", None)
            if order:
                queryset = queryset.order_by(order)
            else:
                queryset = queryset.order_by("-joined_at")

        return queryset

    def perform_destroy(self, instance: Model):
        instance = cast(OrganizationMembership, instance)
        requesting_user = cast(User, self.request.user)
        removed_user = cast(User, instance.user)

        is_self_removal = requesting_user.id == removed_user.id

        posthoganalytics.capture(
            distinct_id=str(requesting_user.distinct_id),
            event="organization member removed",
            properties={
                "removed_member_id": removed_user.distinct_id,
                "removed_by_id": requesting_user.distinct_id,
                "organization_id": instance.organization_id,
                "organization_name": instance.organization.name,
                "removal_type": "self_removal" if is_self_removal else "removed_by_other",
                "removed_email": removed_user.email,
                "removed_user_id": removed_user.id,
            },
            groups=groups(instance.organization),
        )

        instance.user.leave(organization=instance.organization)

    @action(detail=True, methods=["get"])
    def scoped_api_keys(self, request, *args, **kwargs):
        instance = self.get_object()
        api_keys_data = instance.get_scoped_api_keys()

        return Response(
            {
                "has_keys": api_keys_data["has_keys"],
                "has_keys_active_last_week": api_keys_data["has_keys_active_last_week"],
                "keys": api_keys_data["keys"],
            }
        )
