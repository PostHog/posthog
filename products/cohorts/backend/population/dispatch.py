"""Finds population operations that need a worker and gives them one."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone as django_timezone

import structlog

from posthog.dataclasses import frozen

from products.cohorts.backend.models.population import (
    ACTIVE_COHORT_POPULATION_STATUSES,
    CohortPopulationOperation,
    CohortPopulationStatus,
)
from products.cohorts.backend.population import operation as operation_lifecycle
from products.cohorts.backend.population.metrics import COHORT_POPULATION_RECOVERIES
from products.cohorts.backend.population.runner import dispatch_operation

logger = structlog.get_logger(__name__)

MISSED_DISPATCH_GRACE = timedelta(minutes=5)


@frozen
class DispatchPass:
    """What one sweep did, so the caller can log and test it without reading the table again."""

    missed_dispatch: int = 0
    retry_due: int = 0
    lost_worker: int = 0
    reaped_inputs: int = 0

    @property
    def dispatched(self) -> int:
        return self.missed_dispatch + self.retry_due + self.lost_worker


def dispatch_ready_operations() -> DispatchPass:
    now = django_timezone.now()
    limit = settings.COHORT_POPULATION_MAX_DISPATCHES_PER_PASS

    candidates = (
        CohortPopulationOperation.objects.unscoped()
        .filter(status__in=ACTIVE_COHORT_POPULATION_STATUSES)
        .filter(
            Q(status=CohortPopulationStatus.PENDING, dispatched_at__isnull=True)
            | Q(status=CohortPopulationStatus.PENDING, dispatched_at__lte=now - MISSED_DISPATCH_GRACE)
            | Q(status=CohortPopulationStatus.RETRY_SCHEDULED, next_attempt_at__lte=now)
            | Q(status=CohortPopulationStatus.RUNNING, lease_expires_at__lte=now)
        )
        .order_by("created_at")[:limit]
    )

    counts = {"missed_dispatch": 0, "retry_due": 0, "lost_worker": 0}
    for operation in candidates:
        reason = _reason_for(operation, now)
        counts[reason] += 1
        COHORT_POPULATION_RECOVERIES.labels(reason=reason).inc()
        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(dispatched_at=now)
        dispatch_operation(operation.pk)
        logger.info(
            "cohort_population_dispatched",
            operation_id=str(operation.pk),
            cohort_id=operation.cohort_id,
            team_id=operation.team_id,
            reason=reason,
        )

    return DispatchPass(**counts, reaped_inputs=reap_expired_inputs())


def reap_expired_inputs() -> int:
    """Delete retained identifiers whose retention window has passed."""
    now = django_timezone.now()
    expired = (
        CohortPopulationOperation.objects.unscoped()
        .filter(input_manifest__isnull=False, input_expires_at__lte=now)
        .exclude(status__in=ACTIVE_COHORT_POPULATION_STATUSES)[: settings.COHORT_POPULATION_MAX_DISPATCHES_PER_PASS]
    )

    reaped = 0
    for operation in expired:
        try:
            operation_lifecycle.reap_input(operation)
            reaped += 1
        except Exception:
            logger.exception("cohort_population_input_cleanup_failed", operation_id=str(operation.pk))
    return reaped


def _reason_for(operation: CohortPopulationOperation, now) -> str:
    if operation.status == CohortPopulationStatus.RUNNING:
        return "lost_worker"
    if operation.status == CohortPopulationStatus.RETRY_SCHEDULED:
        return "retry_due"
    return "missed_dispatch"
