"""Publishes static cohort population state as Prometheus gauges."""

from __future__ import annotations

from dataclasses import field
from datetime import timedelta

from django.db.models import Count, Min
from django.utils import timezone as django_timezone

from prometheus_client import CollectorRegistry, Gauge

from posthog.dataclasses import frozen
from posthog.metrics import pushed_metrics_registry

from products.cohorts.backend.models.population import (
    ACTIVE_COHORT_POPULATION_STATUSES,
    RESOLVED_COHORT_POPULATION_STATUSES,
    UNRESOLVED_COHORT_POPULATION_STATUSES,
    CohortPopulationOperation,
    CohortPopulationSource,
    CohortPopulationStatus,
)

RECENT_WINDOW = timedelta(hours=1)

PUSH_JOB_NAME = "cohort_population_observe"

_SOURCES = tuple(CohortPopulationSource)


@frozen
class ObservationPass:
    """One pass's readings of the operations table, before they are published."""

    unresolved_operations: dict[tuple[str, str], int] = field(default_factory=dict)
    oldest_active_age_seconds: dict[tuple[str, str], float] = field(default_factory=dict)
    recent_operations: dict[tuple[str, str], int] = field(default_factory=dict)
    incomplete_imports: dict[str, int] = field(default_factory=dict)


def publish_population_gauges() -> ObservationPass:
    result = _observe()
    with pushed_metrics_registry(PUSH_JOB_NAME) as registry:
        _publish(result, registry)
    return result


def _observe() -> ObservationPass:
    now = django_timezone.now()
    result = ObservationPass()

    # Seed every combination with a zero, so each pass pushes a complete group. A slice left out
    # while it is empty vanishes from the push the moment it drains, and an alert reading it goes
    # from a value to no data rather than to zero.
    for source in _SOURCES:
        result.incomplete_imports[source] = 0
        for status in UNRESOLVED_COHORT_POPULATION_STATUSES:
            result.unresolved_operations[status, source] = 0
        for status in ACTIVE_COHORT_POPULATION_STATUSES:
            result.oldest_active_age_seconds[status, source] = 0.0
        for status in (*RESOLVED_COHORT_POPULATION_STATUSES, CohortPopulationStatus.FAILED):
            result.recent_operations[status, source] = 0

    unresolved = (
        CohortPopulationOperation.objects.unscoped()
        .filter(status__in=UNRESOLVED_COHORT_POPULATION_STATUSES)
        .values("status", "source")
        .annotate(operations=Count("id"), oldest=Min("updated_at"))
    )
    for row in unresolved:
        key = (row["status"], row["source"])
        result.unresolved_operations[key] = row["operations"]
        # A failed operation waits for a person, not for a worker, so its age is not a stall.
        if row["status"] in ACTIVE_COHORT_POPULATION_STATUSES:
            result.oldest_active_age_seconds[key] = (now - row["oldest"]).total_seconds()

    recent = (
        CohortPopulationOperation.objects.unscoped()
        .filter(
            status__in=(*RESOLVED_COHORT_POPULATION_STATUSES, CohortPopulationStatus.FAILED),
            finished_at__gte=now - RECENT_WINDOW,
        )
        .values("status", "source")
        .annotate(operations=Count("id"))
    )
    for row in recent:
        result.recent_operations[row["status"], row["source"]] = row["operations"]

    incomplete = (
        CohortPopulationOperation.objects.unscoped()
        .filter(
            status__in=(CohortPopulationStatus.FAILED, CohortPopulationStatus.ABANDONED),
            finished_at__gte=now - RECENT_WINDOW,
        )
        .values("source")
        .annotate(operations=Count("id"))
    )
    for row in incomplete:
        result.incomplete_imports[row["source"]] = row["operations"]

    return result


def _publish(result: ObservationPass, registry: CollectorRegistry) -> None:
    operations_active = Gauge(
        "posthog_cohort_population_operations_active",
        "Static cohort population operations in each unresolved status, by source",
        ["status", "source"],
        registry=registry,
    )
    oldest_active_age = Gauge(
        "posthog_cohort_population_oldest_active_age_seconds",
        "Time since the least recently updated active population operation made progress, by status and source",
        ["status", "source"],
        registry=registry,
    )
    operations_recent = Gauge(
        "posthog_cohort_population_operations_recent",
        "Population operations that reached a terminal status in the last hour, by status and source",
        ["status", "source"],
        registry=registry,
    )
    incomplete_imports = Gauge(
        "posthog_cohort_population_incomplete_imports",
        "Population operations that ended holding less than they were given, in the last hour, by source",
        ["source"],
        registry=registry,
    )

    for (status, source), operations in result.unresolved_operations.items():
        operations_active.labels(status=status, source=source).set(operations)
    for (status, source), age in result.oldest_active_age_seconds.items():
        oldest_active_age.labels(status=status, source=source).set(age)
    for (status, source), operations in result.recent_operations.items():
        operations_recent.labels(status=status, source=source).set(operations)
    for source, operations in result.incomplete_imports.items():
        incomplete_imports.labels(source=source).set(operations)
