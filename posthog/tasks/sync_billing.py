from celery import shared_task

from posthog.exceptions_capture import capture_exception


@shared_task(ignore_result=True, rate_limit="5/s")
def sync_members_to_billing(organization_id: str) -> None:
    from posthog.models import Organization, OrganizationMembership

    organization = Organization.objects.get(id=organization_id)

    first_owner = organization.members.filter(
        organization_membership__level__gte=OrganizationMembership.Level.OWNER
    ).first()

    if not first_owner:
        capture_exception(Exception(f"Organization has no owner", {"organization_id": organization.id}))
        return

    first_owner.update_billing_organization_users(organization)


@shared_task(ignore_result=True, rate_limit="5/s")
def sync_from_billing(organization_id: str) -> None:
    from posthog.cloud_utils import get_cached_instance_license
    from posthog.models import Organization

    from products.enterprise.backend.billing.billing_manager import BillingManager

    license = get_cached_instance_license()
    billing_manager = BillingManager(license, None)

    organization = Organization.objects.get(id=organization_id)
    billing_manager.get_billing(organization, {})
