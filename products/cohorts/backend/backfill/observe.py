"""Publishes backfill run and chunk state as Prometheus gauges.

The seeder owns the richest telemetry about a run — per chunk, per partition, reconcile liveness —
but all of it is the seeder's own view: counters that restart with the pod, and blind to every
transition Django owns. Supersession, cancellation, a `blocked` run parked on a missing attestation,
and the finalizer's own moves never reach it. These gauges read the runs table instead, so a stalled
run or a chunk that exhausted its retries is visible whichever side put it there, and survives a
seeder deploy.

Read the age gauge with the finalizer's state in mind: while `BEHAVIORAL_BACKFILL_FINALIZER_ENABLED`
is off, a behavioral run that finishes seeding parks in `reconciling`, which counts as active, so
that slice climbs forever for work that is already done. Until the finalizer is on, only the
`seeding`, `awaiting_boundary` and `blocked` slices carry an alertable age.

Deliberately not folded into ``finalize_backfill_runs``: that returns early while the finalizer is
off, and the alerts have to work with it still dark.
"""

from dataclasses import field
from datetime import timedelta

from django.db.models import Count, Min
from django.utils import timezone as django_timezone

from prometheus_client import CollectorRegistry, Gauge

from posthog.dataclasses import frozen
from posthog.metrics import pushed_metrics_registry

from products.cohorts.backend.models.backfill import (
    ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
    TERMINAL_COHORT_BACKFILL_RUN_STATUSES,
    CohortBackfillChunk,
    CohortBackfillChunkStatus,
    CohortBackfillKind,
    CohortBackfillRun,
)

RECENT_WINDOW = timedelta(hours=1)

PUSH_JOB_NAME = "cohort_backfill_observe"

_KINDS = tuple(CohortBackfillKind)


@frozen
class ObservationPass:
    """One pass's readings of the runs table, before they are published."""

    active_runs: dict[tuple[str, str], int] = field(default_factory=dict)
    oldest_active_age_seconds: dict[tuple[str, str], float] = field(default_factory=dict)
    failed_chunks: dict[str, int] = field(default_factory=dict)
    recent_runs: dict[tuple[str, str], int] = field(default_factory=dict)


def publish_backfill_run_gauges() -> ObservationPass:
    """One observation pass over every team's backfill runs and chunks."""
    result = _observe()
    # Pushed, rather than served from the worker's own registry: this is a whole-fleet snapshot, and
    # whichever worker the task lands on is the only one holding it. Every other worker keeps serving
    # whatever it last wrote, and no multiprocess mode reaches across pods, so a `max by (status,
    # kind)` alert stays lit until the task comes back round to the pod with the stale reading. One
    # push under one job name replaces the whole group atomically instead. The tradeoff is this
    # helper's usual one: if beat stops, the pushgateway keeps serving the last push, which
    # `push_time_seconds` covers.
    with pushed_metrics_registry(PUSH_JOB_NAME) as registry:
        _publish(result, registry)
    return result


def _observe() -> ObservationPass:
    now = django_timezone.now()
    result = ObservationPass()

    # Seed every combination with a zero first, so each pass pushes a complete group. A slice left
    # out while it is empty vanishes from the push the moment it drains, and an alert expression
    # reading it goes from a value to no data rather than to zero.
    for kind in _KINDS:
        result.failed_chunks[kind] = 0
        for status in ACTIVE_COHORT_BACKFILL_RUN_STATUSES:
            result.active_runs[(status, kind)] = 0
            result.oldest_active_age_seconds[(status, kind)] = 0.0
        for status in TERMINAL_COHORT_BACKFILL_RUN_STATUSES:
            result.recent_runs[(status, kind)] = 0

    # Cross-team on purpose, like the finalizer: these gauges serve the whole fleet, and there is no
    # per-team consumer. No index serves a team-less status predicate — `cohort_bfr_team_status_idx`
    # is team-prefixed, which is the same reason the finalizer needed `cohort_bfr_reconciling_idx`.
    # Fine while the trigger allowlist is narrow; revisit with a partial index if that widens.
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

    return result


def _publish(result: ObservationPass, registry: CollectorRegistry) -> None:
    runs_active = Gauge(
        "posthog_cohort_backfill_runs_active",
        "Backfill runs in each active status, by backfill kind",
        ["status", "kind"],
        registry=registry,
    )
    oldest_active_run_age = Gauge(
        "posthog_cohort_backfill_oldest_active_run_age_seconds",
        "Age of the oldest backfill run in each active status, by backfill kind",
        ["status", "kind"],
        registry=registry,
    )
    chunks_failed = Gauge(
        "posthog_cohort_backfill_chunks_failed",
        # Retry churn, not wedged work: a chunk under the attempt cap is reclaimed and retried, and
        # one past it takes its whole run out of the active set within a poll. A run wedged that way
        # surfaces as `runs_recent{status="failed"}`.
        "Chunks in `failed` status on a still-active run, by backfill kind — retry activity",
        ["kind"],
        registry=registry,
    )
    runs_recent = Gauge(
        "posthog_cohort_backfill_runs_recent",
        # The one to alert on, not `runs_finalized_total`: supersession, the readiness supersede and
        # the seeder's own `fail_run` all terminalize a run without the finalizer counting it, so
        # that counter measures finalizer throughput while this measures run outcomes.
        "Backfill runs terminalized in the last hour, by terminal status and backfill kind",
        ["status", "kind"],
        registry=registry,
    )

    for (status, kind), runs in result.active_runs.items():
        runs_active.labels(status=status, kind=kind).set(runs)
    for (status, kind), age in result.oldest_active_age_seconds.items():
        oldest_active_run_age.labels(status=status, kind=kind).set(age)
    for kind, chunks in result.failed_chunks.items():
        chunks_failed.labels(kind=kind).set(chunks)
    for (status, kind), runs in result.recent_runs.items():
        runs_recent.labels(status=status, kind=kind).set(runs)
