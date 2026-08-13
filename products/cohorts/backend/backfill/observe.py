"""Publishes backfill run and chunk state as Prometheus gauges.

The seeder owns the richest telemetry about a run — per chunk, per partition, reconcile liveness —
but it is operator-run from a toolbox pod, and vmagent only keeps pod targets carrying
``prometheus.io/scrape`` plus a declared container port. Every ``seeder_*`` metric is therefore
dark. These gauges are the scraped substitute: coarser, but enough to alert on a stalled run or a
chunk that exhausted its retries once automatic triggering means nobody is watching runs by hand.

Deliberately not folded into ``finalize_backfill_runs``: that returns early while
``BEHAVIORAL_BACKFILL_FINALIZER_ENABLED`` is off, and the alerts have to work with the finalizer
still dark.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Count, Min
from django.utils import timezone as django_timezone

from prometheus_client import Gauge

from products.cohorts.backend.models.backfill import (
    ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
    CohortBackfillChunk,
    CohortBackfillChunkStatus,
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunStatus,
)

# `livemax` rather than `max`: with `max`, a value written by a celery process that has since died
# stays in the multiprocess directory forever and pins the gauge — and so the alert — at its last
# reading. `livemax` drops dead processes' samples. (`finalize.py`'s HELD_RUNS_GAUGE still uses
# `max` and carries the same latent issue.)
_MULTIPROCESS_MODE = "livemax"

RUNS_ACTIVE_GAUGE = Gauge(
    "posthog_cohort_backfill_runs_active",
    "Backfill runs in each active status, by backfill kind",
    ["status", "kind"],
    multiprocess_mode=_MULTIPROCESS_MODE,
)

OLDEST_ACTIVE_RUN_AGE_GAUGE = Gauge(
    "posthog_cohort_backfill_oldest_active_run_age_seconds",
    "Age of the oldest backfill run in each active status, by backfill kind",
    ["status", "kind"],
    multiprocess_mode=_MULTIPROCESS_MODE,
)

CHUNKS_FAILED_GAUGE = Gauge(
    "posthog_cohort_backfill_chunks_failed",
    "Chunks in `failed` status on runs that are still active, by backfill kind",
    ["kind"],
    multiprocess_mode=_MULTIPROCESS_MODE,
)

RUNS_RECENT_GAUGE = Gauge(
    "posthog_cohort_backfill_runs_recent",
    "Backfill runs terminalized in the last hour, by terminal status and backfill kind",
    ["status", "kind"],
    multiprocess_mode=_MULTIPROCESS_MODE,
)

RECENT_WINDOW = timedelta(hours=1)

TERMINAL_COHORT_BACKFILL_RUN_STATUSES = (
    CohortBackfillRunStatus.COMPLETED,
    CohortBackfillRunStatus.SUPERSEDED,
    CohortBackfillRunStatus.CANCELLED,
    CohortBackfillRunStatus.FAILED,
)

_KINDS = tuple(CohortBackfillKind)


@dataclass
class ObservationPass:
    """One pass's readings, returned so tests can assert without scraping the registry."""

    active_runs: dict[tuple[str, str], int] = field(default_factory=dict)
    oldest_active_age_seconds: dict[tuple[str, str], float] = field(default_factory=dict)
    failed_chunks: dict[str, int] = field(default_factory=dict)
    recent_runs: dict[tuple[str, str], int] = field(default_factory=dict)


def publish_backfill_run_gauges() -> ObservationPass:
    """One observation pass over every team's backfill runs and chunks."""
    now = django_timezone.now()
    result = ObservationPass()

    # Seed every combination with a zero first. A labelled gauge only written when its slice is
    # non-empty freezes at its last reading once the slice drains, so an alert on a stalled run
    # would stay lit long after the run finished.
    for kind in _KINDS:
        result.failed_chunks[kind] = 0
        for status in ACTIVE_COHORT_BACKFILL_RUN_STATUSES:
            result.active_runs[(status, kind)] = 0
            result.oldest_active_age_seconds[(status, kind)] = 0.0
        for status in TERMINAL_COHORT_BACKFILL_RUN_STATUSES:
            result.recent_runs[(status, kind)] = 0

    # Cross-team on purpose, like the finalizer: these gauges serve the whole fleet, and there is no
    # per-team consumer. `cohort_bfr_team_status_idx` still covers the status predicate.
    for row in (
        CohortBackfillRun.objects.unscoped()
        .filter(status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES)
        .values("status", "backfill_kind")
        .annotate(runs=Count("id"), oldest=Min("created_at"))
    ):
        key = (row["status"], row["backfill_kind"])
        result.active_runs[key] = row["runs"]
        result.oldest_active_age_seconds[key] = max(0.0, (now - row["oldest"]).total_seconds())

    for row in (
        CohortBackfillChunk.objects.unscoped()
        .filter(
            status=CohortBackfillChunkStatus.FAILED,
            run__status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
        )
        .values("run__backfill_kind")
        .annotate(chunks=Count("id"))
    ):
        result.failed_chunks[row["run__backfill_kind"]] = row["chunks"]

    for row in (
        CohortBackfillRun.objects.unscoped()
        .filter(status__in=TERMINAL_COHORT_BACKFILL_RUN_STATUSES, finished_at__gte=now - RECENT_WINDOW)
        .values("status", "backfill_kind")
        .annotate(runs=Count("id"))
    ):
        result.recent_runs[(row["status"], row["backfill_kind"])] = row["runs"]

    _publish(result)
    return result


def _publish(result: ObservationPass) -> None:
    for (status, kind), runs in result.active_runs.items():
        RUNS_ACTIVE_GAUGE.labels(status=status, kind=kind).set(runs)
    for (status, kind), age in result.oldest_active_age_seconds.items():
        OLDEST_ACTIVE_RUN_AGE_GAUGE.labels(status=status, kind=kind).set(age)
    for kind, chunks in result.failed_chunks.items():
        CHUNKS_FAILED_GAUGE.labels(kind=kind).set(chunks)
    for (status, kind), runs in result.recent_runs.items():
        RUNS_RECENT_GAUGE.labels(status=status, kind=kind).set(runs)
