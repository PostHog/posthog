from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog
from celery import shared_task
from prometheus_client import Counter

from posthog.models.uploaded_media import ABANDONED_UPLOAD_AGE, UploadedMedia
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

UPLOADED_MEDIA_ABANDONED_SWEPT_COUNTER = Counter(
    "posthog_uploaded_media_abandoned_swept_total",
    "Pending media uploads discarded because they were never completed.",
    labelnames=["outcome"],
)

# Enough to keep one pass bounded on a bad day, while still draining a backlog over a few runs.
SWEEP_BATCH_SIZE = 1000


def _sweep_abandoned_media_upload(media_id: UUID, cutoff: datetime) -> bool:
    with transaction.atomic():
        media = (
            UploadedMedia.objects.select_for_update(skip_locked=True)
            .filter(pk=media_id, pending=True, created_at__lt=cutoff)
            .first()
        )
        if media is None:
            return False

        # Drop the object first so a storage failure leaves the row for the next pass.
        try:
            if media.media_location:
                object_storage.delete(media.media_location)
        except ObjectStorageError:
            UPLOADED_MEDIA_ABANDONED_SWEPT_COUNTER.labels(outcome="storage_error").inc()
            logger.warning(
                "uploaded_media.abandoned_sweep_storage_failed",
                media_id=str(media.pk),
                team_id=media.team_id,
                exc_info=True,
            )
            return False

        media.delete()
        return True


def sweep_abandoned_media_uploads() -> int:
    """Discard pending uploads nobody completed, and the staged bytes behind them.

    `start_upload` reserves a row and a storage key before the caller has sent anything, so a
    caller that stops there — a crashed agent, an upload that never ran, a rejected file whose
    cleanup failed — leaves both behind. Nothing else revisits them, so without this they
    accumulate for the lifetime of the team.

    Returns the number of rows removed.
    """
    cutoff = timezone.now() - ABANDONED_UPLOAD_AGE
    abandoned_ids = list(
        UploadedMedia.objects.filter(pending=True, created_at__lt=cutoff)
        .order_by("created_at")
        .values_list("pk", flat=True)[:SWEEP_BATCH_SIZE]
    )

    swept = sum(_sweep_abandoned_media_upload(media_id, cutoff) for media_id in abandoned_ids)

    UPLOADED_MEDIA_ABANDONED_SWEPT_COUNTER.labels(outcome="swept").inc(swept)
    if swept:
        logger.info("uploaded_media.abandoned_sweep_completed", swept=swept)
    return swept


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sweep_abandoned_media_uploads_task() -> None:
    sweep_abandoned_media_uploads()
