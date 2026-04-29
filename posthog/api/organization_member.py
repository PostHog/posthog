from typing import cast

from django.db.models import F, Model, Prefetch, QuerySet
from django.shortcuts import get_object_or_404

from django_otp.plugins.otp_totp.models import TOTPDevice
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
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
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.permissions import TimeSensitiveActionPermission, extract_organization
from posthog.utils import posthoganalytics

# Only index-backed orderings are allowed. `-joined_at` is served by the
# `(organization, -joined_at)` composite index; other fields would force a
# full scan + sort and can time out for large organizations.
ALLOWED_ORDERINGS = frozenset({"joined_at", "-joined_at"})
DEFAULT_ORDERING = "-joined_at"


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
    is_guest = serializers.BooleanField(read_only=True)
    guest_grant_count = serializers.SerializerMethodField()

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
            "is_guest",
            "guest_grant_count",
        ]
        read_only_fields = ["id", "joined_at", "updated_at"]

    def get_is_2fa_enabled(self, instance: OrganizationMembership) -> bool:
        # Uses prefetched relations to avoid N+1 queries
        user = instance.user
        has_totp = len(user.totpdevice_set.all()) > 0  # type: ignore[attr-defined]
        has_passkeys_for_2fa = bool(user.passkeys_enabled_for_2fa) and len(user.webauthn_credentials.all()) > 0
        return has_totp or has_passkeys_for_2fa

    def get_has_social_auth(self, instance: OrganizationMembership) -> bool:
        return len(instance.user.social_auth.all()) > 0

    def get_guest_grant_count(self, instance: OrganizationMembership) -> int | None:
        # Only meaningful for guests; null for regular members so the FE doesn't render a
        # confusing "0 grants" badge on every regular member row.
        if not instance.is_guest:
            return None
        from ee.models.rbac.access_control import AccessControl

        return AccessControl.objects.filter(
            organization_member=instance,
            resource="notebook",
        ).count()

    def update(self, instance: OrganizationMembership, validated_data: dict[str, object]) -> OrganizationMembership:
        updated_membership = instance
        raise_errors_on_nested_writes("update", self, validated_data)
        requesting_membership: OrganizationMembership = OrganizationMembership.objects.get(
            organization=updated_membership.organization,
            user=self.context["request"].user,
        )
        for attr, value in validated_data.items():
            if attr == "level":
                requesting_membership.validate_update(
                    updated_membership, cast(OrganizationMembership.Level | None, value)
                )
            setattr(updated_membership, attr, value)
        updated_membership.save()
        return updated_membership


@extend_schema(tags=["core", "platform_features"])
@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="order",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=sorted(ALLOWED_ORDERINGS),
                description=f"Sort order. Defaults to `{DEFAULT_ORDERING}`.",
            ),
        ],
    ),
)
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
        OrganizationMembership.objects.exclude(user__email__endswith=INTERNAL_BOT_EMAIL_SUFFIX)
        .filter(
            user__is_active=True,
            is_guest=False,
        )
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "user__totpdevice_set",
                queryset=TOTPDevice.objects.filter(confirmed=True),
            ),
            Prefetch("user__social_auth", queryset=UserSocialAuth.objects.all()),
            Prefetch(
                "user__webauthn_credentials",
                queryset=WebauthnCredential.objects.filter(verified=True),
            ),
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

            # `?include_guests=true` opts the Guests tab (PR #3) into the same endpoint —
            # the viewset's default queryset excludes guests so regular member flows never
            # have to think about them, and the Guests tab explicitly opts in. Visibility
            # of guests matches visibility of regular members: any member of the org can
            # see them. Mutating actions (promote, remove) are gated separately.
            include_guests = params.get("include_guests", "").lower() in {"true", "1"}
            guests_only = params.get("guests_only", "").lower() in {"true", "1"}
            if guests_only:
                queryset = (
                    OrganizationMembership.objects.filter(
                        organization_id=self.organization_id,
                        is_guest=True,
                        user__is_active=True,
                    )
                    .exclude(user__email__endswith=INTERNAL_BOT_EMAIL_SUFFIX)
                    .select_related("user")
                )
            elif include_guests:
                queryset = (
                    OrganizationMembership.objects.filter(
                        organization_id=self.organization_id,
                        user__is_active=True,
                    )
                    .exclude(user__email__endswith=INTERNAL_BOT_EMAIL_SUFFIX)
                    .select_related("user")
                )

            order = self.request.GET.get("order")
            if order in ALLOWED_ORDERINGS:
                queryset = queryset.order_by(order)
            else:
                queryset = queryset.order_by(DEFAULT_ORDERING)

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

    @action(detail=True, methods=["post"])
    def promote_guest(self, request: Request, *args, **kwargs) -> Response:
        """Promote a guest membership to a regular member.

        Deletes all `AccessControl` rows scoped to this membership and flips the `is_guest`
        flag. The caller-facing UI should warn that promotion resets the user's access
        controls — after promotion, the new regular member has no explicit AC rows and
        relies on default project access instead. Admin+ only.
        """
        requesting_user = cast(User, request.user)
        # Resolve membership via the full queryset — the default one filters guests out.
        lookup_value = self.kwargs[self.lookup_field]
        membership = get_object_or_404(
            OrganizationMembership.objects.filter(organization_id=self.organization_id),
            **{self.lookup_field: lookup_value},
        )

        try:
            requesting_membership = OrganizationMembership.objects.get(
                organization_id=membership.organization_id,
                user=requesting_user,
            )
        except OrganizationMembership.DoesNotExist:
            raise exceptions.PermissionDenied("You must be a member of this organization.")
        if requesting_membership.level < OrganizationMembership.Level.ADMIN:
            raise exceptions.PermissionDenied("Only organization admins and owners can promote guests.")

        from posthog.rbac.guest_grants import promote_to_member

        removed = promote_to_member(membership, by=requesting_user)
        return Response({"is_guest": False, "removed_grants": removed})
