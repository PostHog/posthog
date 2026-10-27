"""Daily metric run counters, split by the surface that sent the run."""

from collections.abc import Iterable
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

import structlog

from posthog.event_usage import AGENT_EVENT_SOURCES, get_event_source
from posthog.models import Team

from ..facade.contracts import MetricRunCounts
from ..models import Metric, MetricRunCount

if TYPE_CHECKING:
    from rest_framework.request import Request

logger = structlog.get_logger(__name__)

INTERNAL_RUN_SOURCE = "internal"

RUN_COUNT_WINDOW_DAYS = 30

_AI_SOURCES = sorted(str(source) for source in AGENT_EVENT_SOURCES)


def record_metric_run(team: Team, metric: Metric, request: "Request | None") -> None:
    """Add one run to today's counter. A failed write is logged and dropped, never raised, because
    the count is evidence for reviewers and must not fail the run the caller already paid for."""
    source = str(get_event_source(request)) if request is not None else INTERNAL_RUN_SOURCE
    try:
        _increment(team, metric, source)
    except Exception:
        logger.exception("data_catalog.metric_run_count_failed", team_id=team.id, metric_id=str(metric.id))


def _increment(team: Team, metric: Metric, source: str) -> None:
    today = timezone.now().date()
    counters = MetricRunCount.objects.for_team(team.id).filter(metric=metric, date=today, source=source)
    if counters.update(count=F("count") + 1):
        return
    try:
        # The savepoint keeps a lost race from aborting a transaction the caller may hold open.
        with transaction.atomic():
            MetricRunCount.objects.for_team(team.id).create(
                team=team, metric=metric, date=today, source=source, count=1
            )
    except IntegrityError:
        # A concurrent run created today's row first, so the row now exists to increment.
        counters.update(count=F("count") + 1)


def run_counts_for_metrics(team_id: int, metric_ids: Iterable[UUID]) -> dict[UUID, MetricRunCounts]:
    """Runs in the last 30 days per metric, in one query for the whole set. Metrics with no runs
    in the window are absent from the result."""
    since = timezone.now().date() - timedelta(days=RUN_COUNT_WINDOW_DAYS - 1)
    rows = (
        MetricRunCount.objects.for_team(team_id)
        .filter(metric_id__in=list(metric_ids), date__gte=since)
        .values("metric_id")
        .annotate(
            runs=Sum("count"),
            ai_runs=Sum("count", filter=Q(source__in=_AI_SOURCES), default=0),
        )
    )
    return {row["metric_id"]: MetricRunCounts(runs=row["runs"], ai_runs=row["ai_runs"]) for row in rows}
