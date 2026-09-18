from typing import Any, Optional

from celery import shared_task
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.scoping_audit import skip_team_scope_audit

ORGANIZATION_FEATURE_SYNC_COUNTER = Counter(
    "organization_available_product_features_sync_total",
    "Entitlement re-reads from the billing service, by whether the cached feature set moved.",
    labelnames=["outcome"],
)


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


@shared_task(ignore_result=True, rate_limit="5/s")
@skip_team_scope_audit
def sync_available_product_features_from_billing(organization_id: str) -> None:
    from posthog.cloud_utils import get_cached_instance_license
    from posthog.models import Organization

    from ee.billing.billing_manager import BillingManager

    organization = Organization.objects.get(id=organization_id)
    previous_feature_keys = _feature_keys(organization.available_product_features)

    license = get_cached_instance_license()
    BillingManager(license).update_available_product_features(organization)

    changed = _feature_keys(organization.available_product_features) != previous_feature_keys
    ORGANIZATION_FEATURE_SYNC_COUNTER.labels(outcome="changed" if changed else "unchanged").inc()


def _feature_keys(available_product_features: Optional[list[dict[str, Any]]]) -> set[Optional[str]]:
    return {feature.get("key") for feature in (available_product_features or []) if feature}
