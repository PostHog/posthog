from celery import shared_task

from sentry_sdk import capture_message


@shared_task(ignore_result=True, rate_limit="5/s")
def sync_members_to_billing(organization_id: str) -> None:
    from posthog.models import Organization, OrganizationMembership

    organization = Organization.objects.get(id=organization_id)

    first_owner = organization.members.filter(
        organization_membership__level__gte=OrganizationMembership.Level.OWNER
    ).first()

    if not first_owner:
        capture_message(f"Organization {organization.id} has no owner", level="error")
        return

    first_owner.update_billing_organization_users(organization)


@shared_task(ignore_result=True, rate_limit="5/s")
def sync_from_billing(organization_id: str) -> None:
    from posthog.models import Organization
    from ee.billing.billing_manager import BillingManager
    from posthog.cloud_utils import get_cached_instance_license

    license = get_cached_instance_license()
    billing_manager = BillingManager(license, None)

    organization = Organization.objects.get(id=organization_id)
    billing_manager.get_billing(organization, {})
