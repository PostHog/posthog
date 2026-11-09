from datetime import UTC, datetime

from django.db.models import Count, Min
from django.db.models.functions import Coalesce

import structlog
from celery import shared_task
from prometheus_client import Gauge

from posthog.schema import AlertCalculationInterval

from posthog.celery_queues import CeleryQueue
from posthog.dataclasses import frozen
from posthog.metrics import pushed_metrics_registry
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)


@frozen
class UnstartedDueAlerts:
    calculation_interval: str
    count: int
    oldest_due_age_seconds: float


def unstarted_due_insight_alerts(now: datetime) -> list[UnstartedDueAlerts]:
    """Due insight alerts that hold no evaluation slot, so no check runs for them, by cadence."""
    # Imported here because celery beat imports this module before the Django app registry is ready.
    from posthog.tasks.alerts.utils import due_insight_alerts_q
    from posthog.temporal.alerts.admission import inflight_alert_ids

    from products.alerts.backend.models.alert import AlertConfiguration

    due = AlertConfiguration.objects.filter(due_insight_alerts_q(now))
    try:
        in_flight = inflight_alert_ids()
    except Exception:
        # Without the slot set, running checks count as unstarted. A small overcount still lets a stall show.
        logger.exception("insight_alert_backlog.inflight_read_failed")
        in_flight = set()
    if in_flight:
        due = due.exclude(id__in=in_flight)

    rows = {
        row["calculation_interval"] or "unknown": row
        for row in due.values("calculation_interval").annotate(
            count=Count("id"), oldest_due_at=Min(Coalesce("next_check_at", "created_at"))
        )
    }
    # Every cadence gets a series, so an alert rule on a quiet cadence reads 0 rather than no data.
    intervals = sorted({interval.value for interval in AlertCalculationInterval} | rows.keys())
    backlog = []
    for interval in intervals:
        row = rows.get(interval)
        oldest_due_at = row["oldest_due_at"] if row else None
        backlog.append(
            UnstartedDueAlerts(
                calculation_interval=interval,
                count=row["count"] if row else 0,
                oldest_due_age_seconds=max((now - oldest_due_at).total_seconds(), 0) if oldest_due_at else 0.0,
            )
        )
    return backlog


# Runs on Celery, not Temporal. The scheduler workflow pushes its own due gauges, so a scheduler that
# runs seldom or not at all also stops the report that would show the stall.
@shared_task(ignore_result=True, queue=CeleryQueue.STATS.value)
@skip_team_scope_audit
def record_insight_alert_backlog() -> None:
    backlog = unstarted_due_insight_alerts(datetime.now(UTC))
    with pushed_metrics_registry("celery_insight_alert_backlog") as registry:
        count = Gauge(
            "posthog_insight_alerts_unstarted_due_count",
            "Due insight alerts with no running check, by calculation interval",
            labelnames=["calculation_interval"],
            registry=registry,
        )
        oldest_age = Gauge(
            "posthog_insight_alerts_unstarted_oldest_due_age_seconds",
            "Seconds since the oldest due insight alert with no running check became due, by calculation interval",
            labelnames=["calculation_interval"],
            registry=registry,
        )
        for entry in backlog:
            count.labels(calculation_interval=entry.calculation_interval).set(entry.count)
            oldest_age.labels(calculation_interval=entry.calculation_interval).set(entry.oldest_due_age_seconds)
