from collections.abc import Sequence
from typing import cast

from posthog.cloud_utils import is_cloud
from posthog.models.organization import Organization


def sync_all_organization_available_product_features() -> None:
    if is_cloud():
        return
    for organization in cast(Sequence[Organization], Organization.objects.all().only("id")):
        organization.update_available_product_features()
        organization.save(update_fields=["available_product_features"])
