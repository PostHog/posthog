from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from posthog.cloud_utils import get_cached_instance_license, is_cloud
from posthog.models.organization import Organization

# Every org is re-read once a day. The shard keeps each hourly run small, because each org in
# it costs one request to the billing service.
SHARD_COUNT = 24


def sync_all_organization_available_product_features() -> None:
    if is_cloud():
        _queue_cloud_organization_syncs()
        return

    for organization in cast(Sequence[Organization], Organization.objects.all().only("id")):
        organization.update_available_product_features()
        organization.save(update_fields=["available_product_features"])


def _queue_cloud_organization_syncs() -> None:
    """On cloud the billing service owns entitlements, so re-read them instead of the license."""
    from posthog.tasks.sync_billing import sync_available_product_features_from_billing

    license = get_cached_instance_license()
    if not license or not license.is_v2_license:
        return

    shard = datetime.now(UTC).hour % SHARD_COUNT
    for organization_id in (
        Organization.objects.filter(customer_id__isnull=False).values_list("id", flat=True).iterator(chunk_size=1000)
    ):
        if organization_id.int % SHARD_COUNT == shard:
            sync_available_product_features_from_billing.delay(str(organization_id))
