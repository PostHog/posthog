from datetime import timedelta

from django.utils import timezone

from celery import shared_task

from ee.models.scim_request_log import SCIM_REQUEST_LOG_RETENTION_DAYS, SCIMRequestLog


@shared_task(ignore_result=True)
def cleanup_old_scim_request_logs() -> None:
    cutoff = timezone.now() - timedelta(days=SCIM_REQUEST_LOG_RETENTION_DAYS)
    SCIMRequestLog.objects.filter(created_at__lt=cutoff).delete()
