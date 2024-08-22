from celery import shared_task

from posthog.models import Organization, OrganizationMembership
from sentry_sdk import capture_message


@shared_task(ignore_result=True, rate_limit="3/s")
def sync_to_billing(organization_id: str) -> None:
    organization = Organization.objects.get(id=organization_id)

    first_owner = organization.members.filter(
        organization_membership__level__gte=OrganizationMembership.Level.OWNER
    ).first()

    if not first_owner:
        capture_message(f"Organization {organization.id} has no owner", level="error")
        return

    first_owner.update_billing_organization_users(organization)
