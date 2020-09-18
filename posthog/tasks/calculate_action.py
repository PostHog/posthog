import logging
import time

import posthoganalytics
from celery import shared_task
from django.utils import timezone

from posthog.models import Event
from posthog.utils import get_machine_id

logger = logging.getLogger(__name__)


def status_report() -> None:
    period_end = (timezone.now() - timezone.timedelta(timezone.now().weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )  # very start of the current Monday
    period_start = period_end - timezone.timedelta(7)  # very start of the Monday preceding the current one
    events_considered = Event.objects.filter(created_at__gte=period_start, created_at_lt=period_end)
    report = {"period": [period_start.isoformat(), period_end.isoformat()], "event_count": events_considered.count()}
    posthoganalytics.capture(get_machine_id(), "instance status report", report)
