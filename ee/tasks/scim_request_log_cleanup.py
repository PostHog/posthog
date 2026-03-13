from datetime import timedelta

from django.utils import timezone

from celery import shared_task

from ee.models.scim_request_log import SCIM_REQUEST_LOG_RETENTION_DAYS, SCIMRequestLog

CLEANUP_BATCH_SIZE = 1000


@shared_task(ignore_result=True)
def cleanup_old_scim_request_logs() -> None:
    cutoff = timezone.now() - timedelta(days=SCIM_REQUEST_LOG_RETENTION_DAYS)
    while True:
        batch = list(
            SCIMRequestLog.objects.filter(created_at__lt=cutoff).values_list("id", flat=True)[:CLEANUP_BATCH_SIZE]
        )
        if not batch:
            break
        SCIMRequestLog.objects.filter(id__in=batch).delete()
