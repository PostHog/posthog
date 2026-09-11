from datetime import timedelta

from django.utils import timezone

from celery import shared_task

from posthog.models.messaging import MESSAGING_RECORD_RETENTION_DAYS, MessagingRecord
from posthog.scoping_audit import skip_team_scope_audit

CLEANUP_BATCH_SIZE = 1000
# The table has never been pruned, so the first sweeps work through years of rows. Capping a
# run lets the backlog drain over days instead of holding a worker for hours; steady-state
# volume is far below one run's budget.
CLEANUP_MAX_ROWS_PER_RUN = 250_000


@shared_task(ignore_result=True)
@skip_team_scope_audit
def cleanup_old_messaging_records() -> None:
    cutoff = timezone.now() - timedelta(days=MESSAGING_RECORD_RETENTION_DAYS)
    deleted = 0
    while deleted < CLEANUP_MAX_ROWS_PER_RUN:
        batch = list(
            MessagingRecord.objects.filter(created_at__lt=cutoff).values_list("id", flat=True)[:CLEANUP_BATCH_SIZE]
        )
        if not batch:
            break
        MessagingRecord.objects.filter(id__in=batch).delete()
        deleted += len(batch)
