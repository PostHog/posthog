from datetime import timedelta

from django.utils import timezone

from celery import shared_task

from posthog.models.ssf import SSFEvent
from posthog.scoping_audit import skip_team_scope_audit
from posthog.ssf.validation import RETENTION_DAYS


@shared_task(ignore_result=True)
@skip_team_scope_audit
def cleanup_ssf_events() -> None:
    # Keep replay tombstones for the full accepted issue-time window, including clock skew.
    cutoff = timezone.now() - timedelta(days=RETENTION_DAYS, minutes=5)
    while True:
        batch = list(SSFEvent.objects.filter(created_at__lt=cutoff).values_list("id", flat=True)[:1000])
        if not batch:
            return
        SSFEvent.objects.filter(id__in=batch).delete()
