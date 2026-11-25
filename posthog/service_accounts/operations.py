from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, ServiceAccountState, User
from posthog.models.oauth import (
    OAuthAccessToken,
    OAuthDeviceGrant,
    OAuthGrant,
    OAuthIDToken,
    OAuthRefreshToken,
    lock_oauth_connection,
)
from posthog.models.user import UserType
from posthog.models.utils import strict_fetch
from posthog.service_accounts.emails import generated_service_account_email


def service_accounts(organization: Organization, *, include_deleted: bool = False) -> QuerySet[OrganizationMembership]:
    queryset = (
        OrganizationMembership.objects.filter(organization=organization, user__type=UserType.SERVICE_ACCOUNT)
        .select_related("user", "organization", "user__service_account_state")
        .order_by("-joined_at", "id")
    )
    if not include_deleted:
        queryset = queryset.filter(user__service_account_state__deleted_at__isnull=True)
    return strict_fetch(queryset)


def create_service_account(organization: Organization, *, name: str) -> OrganizationMembership:
    with transaction.atomic():
        user_uuid = uuid4()
        user = User.objects.create_user(
            email=generated_service_account_email(user_uuid),
            password=None,
            first_name=name,
            uuid=user_uuid,
            type=UserType.SERVICE_ACCOUNT,
            allow_impersonation=False,
            current_organization=organization,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return OrganizationMembership.objects.create(
            user=user, organization=organization, level=OrganizationMembership.Level.MEMBER
        )


def rename_service_account(organization: Organization, account_id: UUID, *, name: str) -> OrganizationMembership:
    with transaction.atomic():
        membership = (
            service_accounts(organization)
            .select_for_update(of=("self", "user"), no_key=True)
            .get(user__uuid=account_id)
        )
        membership.user.first_name = name
        membership.user.save(update_fields=["first_name"])
        return membership


def set_service_account_active(
    organization: Organization, account_id: UUID, *, is_active: bool
) -> OrganizationMembership:
    with transaction.atomic():
        membership = (
            service_accounts(organization)
            .select_for_update(of=("self", "user"), no_key=True)
            .get(user__uuid=account_id)
        )
        membership.user.is_active = is_active
        membership.user.save(update_fields=["is_active"])
        return membership


def delete_service_account(organization: Organization, account_id: UUID) -> None:
    with transaction.atomic():
        membership = (
            service_accounts(organization, include_deleted=True)
            .select_for_update(of=("self", "user"), no_key=True)
            .get(user__uuid=account_id)
        )
        user = membership.user
        state, _ = ServiceAccountState.objects.get_or_create(user=user, organization=organization)
        if state.deleted_at is None:
            state.deleted_at = timezone.now()
            state.save(update_fields=["deleted_at"])
        user.is_active = False
        user.save(update_fields=["is_active"])

        application_ids = set(OAuthRefreshToken.objects.filter(user=user).values_list("application_id", flat=True))
        for application_id in sorted(application_ids):
            lock_oauth_connection(user_id=user.pk, application_id=application_id)
        # Delete grants before tokens so an in-flight code exchange cannot escape revocation.
        OAuthGrant.objects.filter(user=user).delete()
        OAuthDeviceGrant.objects.filter(user=user).delete()
        # Revoked refresh-token rows can still authenticate during the rotation grace period.
        OAuthRefreshToken.objects.filter(user=user).delete()
        OAuthAccessToken.objects.filter(user=user).delete()
        OAuthIDToken.objects.filter(user=user).delete()
        for key in PersonalAPIKey.objects.filter(user=user):
            key.delete()


def restore_service_account(organization: Organization, account_id: UUID) -> OrganizationMembership:
    with transaction.atomic():
        membership = (
            service_accounts(organization, include_deleted=True)
            .select_for_update(of=("self", "user"), no_key=True)
            .get(user__uuid=account_id)
        )
        state = ServiceAccountState.objects.filter(user=membership.user, organization=organization).first()
        if state and state.deleted_at is not None:
            state.deleted_at = None
            state.save(update_fields=["deleted_at"])
            membership.user.is_active = True
            membership.user.save(update_fields=["is_active"])
            membership.user.service_account_state = state
        return membership
