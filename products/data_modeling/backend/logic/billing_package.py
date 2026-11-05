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
def update_organization_billing_package(organization_id: str, has_paid_package: bool | None) -> bool:
    if has_paid_package is None:
        return False
    policy, created = OrganizationRefreshPolicy.objects.get_or_create(
        organization_id=organization_id, defaults={"has_paid_package": has_paid_package}
    )
    if created:
        return True
    policy = OrganizationRefreshPolicy.objects.select_for_update().get(organization_id=organization_id)
    if policy.has_paid_package == has_paid_package:
        return False
    policy.has_paid_package = has_paid_package
    policy.save(update_fields=["has_paid_package"])
    return True
