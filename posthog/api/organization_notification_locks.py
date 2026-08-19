from typing import cast

from django.db import transaction

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, User
from posthog.models.organization_notification_lock import (
    LOCKABLE_NOTIFICATION_SETTINGS,
    OrganizationMemberNotificationLock,
)
from posthog.permissions import OrganizationAdminReadPermissions, PostHogFeatureFlagPermission, PremiumFeaturePermission

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)

ORG_NOTIFICATION_GOVERNANCE_FLAG = "org-notification-governance"

# Bounds one save. Far above what the page can produce, since it renders one control per member
# and lockable setting.
MAX_CHANGES_PER_REQUEST = 2000

NOTIFICATION_SETTINGS_URL = "/settings/user-notifications"

# The viewset defines a `list` action, which shadows the builtin inside the class body, so
# annotations there go through these aliases.
_Memberships = list[OrganizationMembership]
_Members = list[dict]


class OrganizationNotificationLockSerializer(serializers.Serializer):
    setting = serializers.ChoiceField(
        choices=sorted(LOCKABLE_NOTIFICATION_SETTINGS),
        help_text="Notification setting this lock enforces.",
    )
    scope_id = serializers.CharField(
        allow_blank=True,
        help_text="What the setting applies to: a project ID, pipeline ID, or organization ID. Empty for a setting that is a single switch.",
    )
    locked_value = serializers.BooleanField(help_text="The value the organization enforces.")
    applies_to_all_members = serializers.BooleanField(
        help_text="True when the lock covers every member, including members who join later."
    )


class OrganizationNotificationMemberSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="Numeric ID of the member, used as the key when saving changes.")
    uuid = serializers.UUIDField(help_text="Stable public identifier of the member.")
    first_name = serializers.CharField(help_text="Member's first name, for display.")
    last_name = serializers.CharField(help_text="Member's last name, for display.")
    email = serializers.EmailField(help_text="Member's email address, which is where these notifications go.")
    organization_membership_level = serializers.IntegerField(
        help_text="Member's organization membership level: 1 for member, 8 for admin, 15 for owner."
    )
    editable = serializers.BooleanField(
        help_text="False when the member's membership level is above yours, which means you cannot change their settings."
    )
    notification_settings = serializers.DictField(
        help_text="The member's own stored notification settings, before any locks apply."
    )
    locks = OrganizationNotificationLockSerializer(
        many=True,
        help_text="Locks in force for this member, including organization-wide ones they inherit.",
    )


class OrganizationNotificationLockChangeSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(
        allow_null=True,
        help_text="Member to change. Null applies the change to every member, including future joiners.",
    )
    setting = serializers.ChoiceField(
        choices=sorted(LOCKABLE_NOTIFICATION_SETTINGS),
        help_text="Notification setting to lock or unlock.",
    )
    scope_id = serializers.CharField(
        allow_blank=True,
        default="",
        help_text="What the setting applies to. Empty for a setting that is a single switch.",
    )
    locked_value = serializers.BooleanField(
        allow_null=True,
        help_text="Value to enforce, or null to remove the lock and give the member their own choice back.",
    )


class OrganizationNotificationLockBulkUpdateSerializer(serializers.Serializer):
    changes = serializers.ListField(
        child=OrganizationNotificationLockChangeSerializer(),
        allow_empty=False,
        max_length=MAX_CHANGES_PER_REQUEST,
        help_text="Only the entries you changed. Anything left out keeps whatever it had.",
    )


def _represent_lock(lock: OrganizationMemberNotificationLock) -> dict:
    return {
        "setting": lock.setting,
        "scope_id": lock.scope_id,
        "locked_value": lock.locked_value,
        "applies_to_all_members": lock.organization_membership_id is None,
    }


def _notify(user: User, organization: Organization, change_count: int) -> None:
    settings_or_setting = "1 setting" if change_count == 1 else f"{change_count} settings"
    create_notification(
        NotificationData(
            organization_id=organization.id,
            notification_type=NotificationType.NOTIFICATION_SETTINGS_CHANGED,
            priority=Priority.NORMAL,
            title="Your notification settings changed",
            body=(
                f"An admin of {organization.name} set {settings_or_setting} for you. "
                "You can see what applies in Settings, under Account, Notifications."
            ),
            target_type=TargetType.USER,
            target_id=str(user.id),
            source_url=NOTIFICATION_SETTINGS_URL,
        )
    )


@extend_schema(extensions={"x-product": "core"})
class OrganizationNotificationLockViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    permission_classes = [OrganizationAdminReadPermissions, PremiumFeaturePermission, PostHogFeatureFlagPermission]
    premium_feature = AvailableFeature.ORGANIZATION_SECURITY_SETTINGS
    posthog_feature_flag = ORG_NOTIFICATION_GOVERNANCE_FLAG
    pagination_class = None

    @extend_schema(
        responses={200: OrganizationNotificationMemberSerializer(many=True)},
        description="List the organization's members with their own notification settings and the locks in force for each.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        return Response(self._represent_members())

    @extend_schema(
        request=OrganizationNotificationLockBulkUpdateSerializer,
        responses={200: OrganizationNotificationMemberSerializer(many=True)},
        description="Lock or unlock notification settings for members of this organization. Each affected member is notified in the app.",
    )
    @action(methods=["POST"], detail=False, url_path="bulk_update")
    def bulk_update(self, request: Request, **kwargs) -> Response:
        serializer = OrganizationNotificationLockBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        memberships = {membership.user_id: membership for membership in self._memberships()}
        actor_level = self._actor_level()
        affected_user_ids: set[int] = set()

        with transaction.atomic():
            for change in serializer.validated_data["changes"]:
                membership = None
                if change["user_id"] is not None:
                    membership = memberships.get(change["user_id"])
                    if membership is None:
                        raise serializers.ValidationError(
                            f"User {change['user_id']} is not a member of this organization",
                            code="invalid_input",
                        )
                    if membership.level > actor_level:
                        raise PermissionDenied(
                            f"Your organization access level is insufficient to change settings for {membership.user.email}"
                        )
                    affected_user_ids.add(membership.user_id)
                else:
                    affected_user_ids.update(
                        user_id for user_id, member in memberships.items() if member.level <= actor_level
                    )

                self._apply_change(change, membership)

        for user_id in sorted(affected_user_ids):
            _notify(memberships[user_id].user, self.organization, len(serializer.validated_data["changes"]))

        return Response(self._represent_members())

    def _apply_change(self, change: dict, membership: OrganizationMembership | None) -> None:
        lookup = {
            "organization_id": self.organization.id,
            "organization_membership": membership,
            "setting": change["setting"],
            "scope_id": change.get("scope_id") or "",
        }
        if change["locked_value"] is None:
            OrganizationMemberNotificationLock.objects.filter(**lookup).delete()
            return

        OrganizationMemberNotificationLock.objects.update_or_create(
            **lookup,
            defaults={"locked_value": change["locked_value"], "created_by": cast(User, self.request.user)},
        )

    def _memberships(self) -> _Memberships:
        return list(
            OrganizationMembership.objects.select_related("user")
            .filter(organization_id=self.organization.id)
            .order_by("user__email")
        )

    def _actor_level(self) -> int:
        membership = OrganizationMembership.objects.filter(
            user=cast(User, self.request.user), organization_id=self.organization.id
        ).first()
        return membership.level if membership else OrganizationMembership.Level.MEMBER

    def _represent_members(self) -> _Members:
        actor_level = self._actor_level()
        locks = list(OrganizationMemberNotificationLock.objects.filter(organization_id=self.organization.id))
        org_wide = [lock for lock in locks if lock.organization_membership_id is None]
        by_membership: dict[str, list[OrganizationMemberNotificationLock]] = {}
        for lock in locks:
            if lock.organization_membership_id is not None:
                by_membership.setdefault(str(lock.organization_membership_id), []).append(lock)

        members = []
        for membership in self._memberships():
            own = by_membership.get(str(membership.id), [])
            overridden = {(lock.setting, lock.scope_id) for lock in own}
            inherited = [lock for lock in org_wide if (lock.setting, lock.scope_id) not in overridden]
            members.append(
                {
                    "user_id": membership.user_id,
                    "uuid": membership.user.uuid,
                    "first_name": membership.user.first_name,
                    "last_name": membership.user.last_name,
                    "email": membership.user.email,
                    "organization_membership_level": membership.level,
                    "editable": membership.level <= actor_level,
                    "notification_settings": membership.user.notification_settings,
                    "locks": [_represent_lock(lock) for lock in own + inherited],
                }
            )
        return members
