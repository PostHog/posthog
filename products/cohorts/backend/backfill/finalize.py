"""Terminalizes behavioral backfill runs the Rust seeder has fully observed.

Only ``last_backfill_events_at`` is stamped; mixed person+behavioral cohorts stay flag-incompatible
until the person-properties column is stamped too (intended fail-closed).

The seeder writes a definitive per-participation outcome (``reconcile_completed_at`` /
``superseded_at`` / retryable ``error``) before it sets ``run.reconcile_observed_at`` as its last
write. This finalizer trusts those columns — never Kafka — and CASes the run out of
``reconciling`` once every participation has a terminal outcome.
"""

from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Now

import structlog
from celery import current_app
from prometheus_client import Counter, Gauge

from posthog.tasks.utils import CeleryQueue

from products.cohorts.backend.backfill.readiness import stamp_events_readiness
from products.cohorts.backend.models.backfill import (
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillScope,
)
from products.cohorts.backend.models.dependencies import invalidate_team_behavioral_cohort_cache

logger = structlog.get_logger(__name__)

# products.feature_flags already depends on products.cohorts, so a static import of its task here
# would close a forbidden product-dependency cycle; dispatch by registered task name instead. The
# task pins the same string via ``name=`` so moving its module can't silently rename it out from
# under us; test_finalize.py asserts the two still agree.
FLAGS_CACHE_TASK = "products.feature_flags.backend.tasks.update_team_service_flags_cache"

READINESS_STAMPS_COUNTER = Counter(
    "posthog_cohort_backfill_readiness_stamps_total",
    "Backfill participations resolved by the finalizer, by outcome",
    ["result"],  # labels: "stamped", "superseded"
)

RUNS_FINALIZED_COUNTER = Counter(
    "posthog_cohort_backfill_runs_finalized_total",
    "Backfill runs terminalized by the finalizer, by terminal status",
    ["status"],  # labels: "completed", "superseded"
)

# Split by reason: a shortfall is routine backpressure, an error is a crashed pass. Summing them
# would leave an alert unable to tell which one is happening.
HELD_RUNS_GAUGE = Gauge(
    "posthog_cohort_backfill_finalizer_held_runs",
    "Observed backfill runs the finalizer left in reconciling, by reason",
    ["reason"],  # labels: "shortfall" (an outcome was missing), "error" (the pass raised)
    multiprocess_mode="max",
)


@dataclass
class FinalizerPass:
    runs_scanned: int = 0
    completed: int = 0
    superseded: int = 0
    held: int = 0
    errored: int = 0
    stamped_participations: int = 0
    invalidated_teams: int = 0


def _dispatch_flags_cache_update(team_id: int) -> None:
    # send_task bypasses the task decorator's options, so the queue must be routed explicitly.
    current_app.send_task(FLAGS_CACHE_TASK, args=(team_id,), queue=CeleryQueue.FEATURE_FLAGS.value)


def finalize_backfill_runs() -> FinalizerPass:
    """One finalizer pass. Returns a summary so callers/tests can assert without scraping logs."""
    result = FinalizerPass()
    if not settings.BEHAVIORAL_BACKFILL_FINALIZER_ENABLED:
        # Reset rather than leave the gauge frozen at its last value: multiprocess_mode="max" keeps
        # a stale reading alive fleet-wide until the process recycles.
        _publish_held_runs(result)
        return result

    # Deliberate, documented cross-team scan: the finalizer serves all teams. Each row is re-locked
    # per team inside the loop, so the unscoped read is discovery only. Oldest-observed first, which
    # the partial index already orders by, so a capped pass drains the backlog in arrival order.
    observed = list(
        CohortBackfillRun.objects.unscoped()
        .filter(
            # Only the events column is stamped, so never terminalize a person-properties run.
            backfill_kind=CohortBackfillKind.BEHAVIORAL,
            status=CohortBackfillRunStatus.RECONCILING,
            reconcile_observed_at__isnull=False,
        )
        .order_by("reconcile_observed_at")
        .values_list("id", "team_id")[: settings.BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS]
    )

    teams_to_invalidate: set[int] = set()
    for run_id, team_id in observed:
        try:
            invalidate_team = _finalize_one_run(run_id, team_id, result)
        except Exception:
            # The transaction rolled back, so the run is still reconciling — count it so the pager
            # gauge reflects a stuck run rather than reading clean.
            logger.exception("cohort_backfill_finalizer_run_error", run_id=str(run_id), team_id=team_id)
            result.errored += 1
            continue
        if invalidate_team:
            teams_to_invalidate.add(team_id)

    # Invalidation bypasses the cohort save signals, so it must run explicitly once per team, and only
    # after the per-run transactions have committed.
    for team_id in teams_to_invalidate:
        try:
            invalidate_team_behavioral_cohort_cache(team_id)
            _dispatch_flags_cache_update(team_id)
        except Exception:
            logger.exception("cohort_backfill_finalizer_cache_invalidation_failed", team_id=team_id)
            continue
        result.invalidated_teams += 1

    _publish_held_runs(result)
    return result


def _publish_held_runs(result: FinalizerPass) -> None:
    HELD_RUNS_GAUGE.labels(reason="shortfall").set(result.held)
    HELD_RUNS_GAUGE.labels(reason="error").set(result.errored)


def _finalize_one_run(run_id: UUID, team_id: int, result: FinalizerPass) -> bool:
    """Terminalize one observed run. Returns whether the team's caches need invalidating."""
    stamped = 0
    superseded = 0
    held = 0
    invalidate_team = False
    with transaction.atomic():
        run = (
            CohortBackfillRun.objects.for_team(team_id)
            .select_for_update(skip_locked=True, of=("self",))
            .filter(
                id=run_id,
                status=CohortBackfillRunStatus.RECONCILING,
                reconcile_observed_at__isnull=False,
            )
            .first()
        )
        if run is None:
            # Locked by another worker, or no longer eligible; a later pass retries.
            return False

        result.runs_scanned += 1

        participations = list(CohortBackfillRunCohort.objects.for_team(team_id).filter(run_id=run.id))
        if run.scope == CohortBackfillScope.COHORT and len(participations) != 1:
            # create_backfill_run_for_cohort gives a cohort-scoped run exactly one participation, but
            # no DB constraint holds that. The terminal CAS below reads the invariant, so surface a
            # violation loudly instead of silently miscounting the run.
            logger.error(
                "cohort_backfill_finalizer_cohort_scoped_run_participation_count",
                run_id=str(run.id),
                team_id=team_id,
                participations=len(participations),
            )
        for participation in participations:
            # Supersede trumps completion, so check it first.
            if participation.superseded_at is not None:
                superseded += 1
                continue
            if participation.stamped_at is not None:
                stamped += 1
                continue
            if participation.reconcile_completed_at is not None:
                if stamp_events_readiness(run, participation.cohort_id):
                    stamped += 1
                    invalidate_team = True
                    result.stamped_participations += 1
                    READINESS_STAMPS_COUNTER.labels(result="stamped").inc()
                else:
                    # stamp_events_readiness superseded the participation (and, for a cohort-scoped
                    # run, possibly the run row itself) inside this transaction.
                    superseded += 1
                    READINESS_STAMPS_COUNTER.labels(result="superseded").inc()
                continue

            # No outcome despite reconcile_observed_at being set. An empty error means the seeder
            # observed the run without writing an outcome; a non-empty error is a legitimate
            # retryable shortfall that simply holds until re-dispatch.
            held += 1
            if participation.error == "":
                logger.error(
                    "cohort_backfill_finalizer_participation_missing_outcome",
                    run_id=str(run.id),
                    cohort_id=participation.cohort_id,
                    team_id=team_id,
                )

        if held > 0:
            logger.info(
                "cohort_backfill_finalizer_run_held",
                run_id=str(run.id),
                team_id=team_id,
                stamped=stamped,
                superseded=superseded,
                held=held,
            )
            result.held += 1
            return invalidate_team

        terminal_status = CohortBackfillRunStatus.COMPLETED if stamped >= 1 else CohortBackfillRunStatus.SUPERSEDED
        transitioned = (
            CohortBackfillRun.objects.for_team(team_id)
            .filter(id=run.id, status=CohortBackfillRunStatus.RECONCILING)
            .update(status=terminal_status, finished_at=Now())
        )
        if transitioned:
            if terminal_status == CohortBackfillRunStatus.COMPLETED:
                result.completed += 1
                RUNS_FINALIZED_COUNTER.labels(status="completed").inc()
            else:
                result.superseded += 1
                RUNS_FINALIZED_COUNTER.labels(status="superseded").inc()
        else:
            # We hold the run row's FOR UPDATE lock, so a missed CAS can only mean our own
            # stamp_events_readiness call superseded a cohort-scoped run inside this transaction —
            # the run is terminal (superseded + finished_at) and counted as such. That reads the
            # one-participation invariant checked above: with more, a run that also stamped a cohort
            # would land here and be counted purely superseded.
            result.superseded += 1
            RUNS_FINALIZED_COUNTER.labels(status="superseded").inc()

        # Re-fire invalidation when completing a run whose stamps landed in an earlier pass, covering
        # a crash between that pass's commit and its post-commit invalidation. (A crash after this
        # terminal transition commits leaves any staleness bounded by the flags-cache verifier task
        # and the behavioral-ids cache TTL, in the fail-closed direction.)
        if terminal_status == CohortBackfillRunStatus.COMPLETED and stamped >= 1:
            invalidate_team = True

    return invalidate_team
