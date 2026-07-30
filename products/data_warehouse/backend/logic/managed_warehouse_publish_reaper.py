from datetime import timedelta

from django.utils import timezone

import structlog

from posthog.ducklake.models import ManagedWarehousePublishedTable

logger = structlog.get_logger(__name__)

STALE_AFTER = timedelta(hours=6)
REAP_BATCH_CAP = 1000
STALE_ERROR = "Publishing did not finish within six hours. Try again."


def mark_stale_publications_failed() -> int:
    cutoff = timezone.now() - STALE_AFTER
    stale_ids = list(
        ManagedWarehousePublishedTable.objects.unscoped()
        .filter(
            status__in=[
                ManagedWarehousePublishedTable.Status.PENDING,
                ManagedWarehousePublishedTable.Status.PUBLISHING,
            ],
            deleted=False,
            updated_at__lt=cutoff,
        )
        .values_list("id", flat=True)[:REAP_BATCH_CAP]
    )
    if not stale_ids:
        return 0

    reaped = (
        ManagedWarehousePublishedTable.objects.unscoped()
        .filter(
            id__in=stale_ids,
            status__in=[
                ManagedWarehousePublishedTable.Status.PENDING,
                ManagedWarehousePublishedTable.Status.PUBLISHING,
            ],
            deleted=False,
        )
        .update(
            status=ManagedWarehousePublishedTable.Status.FAILED,
            last_error=STALE_ERROR,
            updated_at=timezone.now(),
        )
    )
    if reaped:
        logger.warning("managed_warehouse_stale_publications_reaped", count=reaped)
    return reaped
