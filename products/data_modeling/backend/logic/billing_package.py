from datetime import datetime
from typing import Literal

from django.db import transaction

from products.data_modeling.backend.models.organization_refresh_policy import OrganizationRefreshPolicy


def organization_package_label(organization_id: str) -> Literal["paid", "none", "unknown"]:
    has_package = (
        OrganizationRefreshPolicy.objects.filter(organization_id=organization_id)
        .values_list("has_paid_package", flat=True)
        .first()
    )
    if has_package is None:
        return "unknown"
    return "paid" if has_package else "none"


@transaction.atomic
def update_organization_billing_package(
    organization_id: str, has_paid_package: bool | None, computed_at: datetime | None = None
) -> bool:
    """Store the package status, unless it is older than the status stored or cannot be ordered against it.

    A billing status only stamps the organization when the organization row changes, so a package-only
    change has to keep its own timestamp for a late, older status not to reverse it. A status without a
    timestamp waits for the next timestamped one once the row has a timestamp.
    """
    if has_paid_package is None:
        return False
    policy, created = OrganizationRefreshPolicy.objects.get_or_create(
        organization_id=organization_id,
        defaults={"has_paid_package": has_paid_package, "billing_status_computed_at": computed_at},
    )
    if created:
        return True
    policy = OrganizationRefreshPolicy.objects.select_for_update().get(organization_id=organization_id)
    applied_at = policy.billing_status_computed_at
    if applied_at is not None and (computed_at is None or computed_at < applied_at):
        return False
    package_changed = policy.has_paid_package != has_paid_package
    if not package_changed and computed_at in (None, applied_at):
        return False
    policy.has_paid_package = has_paid_package
    policy.billing_status_computed_at = computed_at
    policy.save(update_fields=["has_paid_package", "billing_status_computed_at"])
    return package_changed
