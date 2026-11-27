from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import QuerySet

from posthog.models import Organization, OrganizationMembership, User
from posthog.models.user import UserType
from posthog.models.utils import strict_fetch
from posthog.service_accounts.emails import generated_service_account_email


def service_accounts(organization: Organization) -> QuerySet[OrganizationMembership]:
    return strict_fetch(
        OrganizationMembership.objects.filter(organization=organization, user__type=UserType.SERVICE_ACCOUNT)
        .select_related("user", "organization")
        .order_by("-joined_at", "id")
    )


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
        membership = service_accounts(organization).select_for_update(of=("self", "user")).get(user__uuid=account_id)
        membership.user.first_name = name
        membership.user.save(update_fields=["first_name"])
        return membership
