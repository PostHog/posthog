from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.scoping_audit import skip_team_scope_audit


@shared_task(ignore_result=True, rate_limit="5/s")
@skip_team_scope_audit
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
@skip_team_scope_audit
def sync_from_billing(organization_id: str) -> None:
    from posthog.cloud_utils import get_cached_instance_license
    from posthog.models import Organization

    from ee.billing.billing_manager import BillingManager

    license = get_cached_instance_license()
    billing_manager = BillingManager(license, None)

    organization = Organization.objects.get(id=organization_id)
    billing_manager.get_billing(organization, {})


@shared_task(
    ignore_result=True,
    rate_limit="5/s",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
@skip_team_scope_audit
def sync_organization_active_state_to_billing(organization_id: str) -> None:
    """Mirror Organization.is_active into billing's deactivated flag (forecast exclusion)."""
    from posthog.cloud_utils import get_cached_instance_license, is_cloud
    from posthog.models import Organization

    from ee.billing.billing_manager import BillingManager

    if not is_cloud():
        return
    license = get_cached_instance_license()
    if license is None:
        return

    organization = Organization.objects.get(id=organization_id)
    BillingManager(license, None).set_organizations_deactivated(
        [str(organization.id)], deactivated=not organization.is_active
    )


@shared_task(ignore_result=True)
@skip_team_scope_audit
def reconcile_organization_active_state_to_billing() -> None:
    """Nightly sweep: realign billing's deactivated flags with Organization.is_active.

    The post_save signal is the real-time path; this catches missed flips (worker loss,
    writes that skip signals). Organization.is_active is authoritative in both directions,
    so a flag set only in billing for an org that is active here is removed.
    """
    from posthog.cloud_utils import get_cached_instance_license, is_cloud
    from posthog.models import Organization

    from ee.billing.billing_manager import BillingManager

    if not is_cloud():
        return
    license = get_cached_instance_license()
    if license is None:
        return

    manager = BillingManager(license, None)
    billing_deactivated = set(manager.get_deactivated_organizations())
    inactive = {str(pk) for pk in Organization.objects.filter(is_active=False).values_list("id", flat=True)}

    to_deactivate = sorted(inactive - billing_deactivated)
    # Only touch ids this instance knows: billing's list is license-scoped, but an unknown id
    # (e.g. a deleted org) is not ours to flip back.
    to_reactivate = sorted(
        str(pk)
        for pk in Organization.objects.filter(is_active=True, id__in=billing_deactivated).values_list("id", flat=True)
    )
    # Billing caps a batch at 1000 organization ids.
    batch_size = 500
    for batch_start in range(0, len(to_deactivate), batch_size):
        manager.set_organizations_deactivated(to_deactivate[batch_start : batch_start + batch_size], deactivated=True)
    for batch_start in range(0, len(to_reactivate), batch_size):
        manager.set_organizations_deactivated(to_reactivate[batch_start : batch_start + batch_size], deactivated=False)
