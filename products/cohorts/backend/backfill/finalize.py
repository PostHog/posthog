"""Terminalizes backfill runs the Rust seeder has fully observed.

A run stamps the readiness column of its own kind: behavioral runs stamp ``last_backfill_events_at``,
person-property runs stamp ``last_backfill_person_properties_at``. A mixed cohort needs both runs to
finalize before it is flag-compatible (intended fail-closed).

The person half is gated dark by ``BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED`` until the flags
service can tell a stamp written here apart from the legacy ones it currently reads as proof that
``cohort_membership`` is populated. See ``_finalizable_kinds``.

The seeder writes a definitive per-participation outcome (``reconcile_completed_at`` /
``superseded_at`` / retryable ``error``) before it sets ``run.reconcile_observed_at`` as its last
write. This finalizer trusts those columns — never Kafka — and CASes the run out of
``reconciling`` once every participation has a terminal outcome.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Now

import structlog
from celery import current_app
from prometheus_client import Counter, Gauge

from posthog.tasks.utils import CeleryQueue

from products.cohorts.backend.backfill.allowlist import parse_run_allowlist
from products.cohorts.backend.backfill.readiness import stamp_events_readiness, stamp_person_properties_readiness
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
    "Backfill participations resolved by the finalizer, by outcome and backfill kind",
    # Split by kind for the same reason as by result: a person-side supersession spike is invisible
    # summed against behavioral traffic.
    ["result", "kind"],  # result: "stamped", "superseded"; kind: the CohortBackfillKind
)

RUNS_FINALIZED_COUNTER = Counter(
    "posthog_cohort_backfill_runs_finalized_total",
    "Backfill runs terminalized by the finalizer, by terminal status and backfill kind",
    ["status", "kind"],  # status: "completed", "superseded"; kind: the CohortBackfillKind
)

# Split by reason: a shortfall is routine backpressure, an error is a crashed pass, and a gated run
# is an expected backlog waiting on `BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED`. Summing them
# would leave an alert unable to tell which one is happening.
HELD_RUNS_GAUGE = Gauge(
    "posthog_cohort_backfill_finalizer_held_runs",
    "Observed backfill runs the finalizer left in reconciling, by reason",
    # labels: "shortfall" (an outcome was missing), "error" (the pass raised), "gated" (a person
    # run parked behind the readiness gate), "not_allowlisted" (excluded by
    # BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST)
    ["reason"],
    # Each pass is a whole-fleet snapshot, so only the newest reading is correct. `max` pinned the
    # gauge at the highest value any celery process ever wrote, including dead ones, so a backlog
    # that has since drained still reads as full. Widening the allowlist is meant to be watched on
    # `not_allowlisted` going to zero, which `max` could never show. `observe.py` reaches the same
    # end by pushing its gauges under one job name.
    multiprocess_mode="livemostrecent",
)


# Mutable by design: one pass accumulates counters into it as it walks the runs.
@dataclass(frozen=False)
class FinalizerPass:
    runs_scanned: int = 0
    completed: int = 0
    superseded: int = 0
    held: int = 0
    errored: int = 0
    gated: int = 0
    not_allowlisted: int = 0
    stamped_participations: int = 0
    invalidated_teams: int = 0


# Every kind this finalizer knows how to stamp. Discovery draws from these keys, so the lookup below
# can only ever see a kind it has a stamp for, which is what guarantees a run is never stamped into
# the wrong column. It also means a kind added to the vocabulary without a stamp here is filtered out
# of discovery and simply never finalized: it sits in `reconciling` indefinitely, with no exception,
# no error count, and no gauge movement. `test_every_backfill_kind_has_a_stamp` turns that silence
# into a CI failure instead.
_STAMP_BY_KIND: dict[str, Callable[[CohortBackfillRun, int], bool]] = {
    CohortBackfillKind.BEHAVIORAL: stamp_events_readiness,
    CohortBackfillKind.PERSON_PROPERTY: stamp_person_properties_readiness,
}


def _finalizable_kinds() -> tuple[str, ...]:
    """The kinds this pass may terminalize, narrowed by the person readiness gate.

    Gating discovery rather than the stamp is deliberate: a stamp function that returned ``False``
    would mark the participation superseded, which is terminal, and would silently throw away a
    completed person backfill. Filtering here leaves the run `reconciling` instead, so it finalizes
    normally once the gate opens. See ``BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED`` for why the
    person stamp is held back: the flags service still reads it as proof that `cohort_membership`
    is populated, which is true of the legacy rows but not of one this finalizer writes.
    """
    if settings.BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED:
        return tuple(_STAMP_BY_KIND)
    return (CohortBackfillKind.BEHAVIORAL,)


def _dispatch_flags_cache_update(team_id: int) -> None:
    # send_task bypasses the task decorator's options, so the queue must be routed explicitly.
    current_app.send_task(FLAGS_CACHE_TASK, args=(team_id,), queue=CeleryQueue.FEATURE_FLAGS.value)


def finalize_backfill_runs() -> FinalizerPass:
    """One finalizer pass. Returns a summary so callers/tests can assert without scraping logs."""
    result = FinalizerPass()
    if not settings.BEHAVIORAL_BACKFILL_FINALIZER_ENABLED:
        # Reset rather than leave the gauge frozen at its last value: a reason left unwritten while
        # the finalizer is off keeps reporting whatever the last enabled pass observed.
        _publish_held_runs(result)
        return result

    if not settings.BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED:
        # The kind filter below holds these runs invisibly: discovery never surfaces them, so
        # `result.held` stays 0 and nothing else reports how much is waiting behind the gate.
        result.gated = (
            CohortBackfillRun.objects.unscoped()
            .filter(
                backfill_kind=CohortBackfillKind.PERSON_PROPERTY,
                status=CohortBackfillRunStatus.RECONCILING,
                reconcile_observed_at__isnull=False,
            )
            .count()
        )

    # Deliberate, documented cross-team scan: the finalizer serves all teams. Each row is re-locked
    # per team inside the loop, so the unscoped read is discovery only. The kind predicate does two
    # jobs: while `BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED` is off it holds person runs in
    # `reconciling` rather than stamping them, and it is what makes "a kind with no stamp is never
    # discovered", rather than "is discovered and then raises", protect `_STAMP_BY_KIND`.
    #
    # One query per kind, each with its own slice of the budget: the person backlog parked while
    # the readiness gate was off all sorts ahead of live behavioral runs under
    # `reconcile_observed_at`, so a single shared cap would hand it the entire budget for the first
    # passes after the gate opens. Per-kind equality is also what keeps the walk cheap:
    # `cohort_bfr_reconciling_idx` leads with `backfill_kind`, so each query enters the index at its
    # own kind and reads `reconcile_observed_at` already ordered — the cap terminates the walk
    # rather than bounding a sort, and neither kind pays for the other's parked backlog.
    kinds = _finalizable_kinds()
    per_kind = max(1, settings.BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS // len(kinds))
    allowlist = parse_run_allowlist(settings.BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST)
    observed: list[tuple[UUID, int]] = []
    for kind in kinds:
        discovered = CohortBackfillRun.objects.unscoped().filter(
            backfill_kind=kind,
            status=CohortBackfillRunStatus.RECONCILING,
            reconcile_observed_at__isnull=False,
        )
        if allowlist is not None:
            # Filtered in SQL, not in Python afterwards. The `[:per_kind]` slice below applies in the
            # database, so a post-filter would let an excluded backlog consume the whole budget and
            # starve the verified runs — the same starvation the per-kind split above guards against.
            #
            # Count the exclusions rather than leaving them invisible: the filter holds these runs in
            # `reconciling` without touching `result.held`, so nothing else would report how much is
            # waiting on the allowlist being widened.
            result.not_allowlisted += discovered.exclude(id__in=allowlist).count()
            discovered = discovered.filter(id__in=allowlist)
        observed.extend(discovered.order_by("reconcile_observed_at").values_list("id", "team_id")[:per_kind])

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
    HELD_RUNS_GAUGE.labels(reason="gated").set(result.gated)
    HELD_RUNS_GAUGE.labels(reason="not_allowlisted").set(result.not_allowlisted)


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
        stamp_readiness = _STAMP_BY_KIND[run.backfill_kind]
        for participation in participations:
            # Supersede trumps completion, so check it first.
            if participation.superseded_at is not None:
                superseded += 1
                continue
            if participation.stamped_at is not None:
                stamped += 1
                continue
            if participation.reconcile_completed_at is not None:
                if stamp_readiness(run, participation.cohort_id):
                    stamped += 1
                    invalidate_team = True
                    result.stamped_participations += 1
                    READINESS_STAMPS_COUNTER.labels(result="stamped", kind=run.backfill_kind).inc()
                else:
                    # The stamp superseded the participation (and, for a cohort-scoped run, possibly
                    # the run row itself) inside this transaction.
                    superseded += 1
                    READINESS_STAMPS_COUNTER.labels(result="superseded", kind=run.backfill_kind).inc()
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
                RUNS_FINALIZED_COUNTER.labels(status="completed", kind=run.backfill_kind).inc()
            else:
                result.superseded += 1
                RUNS_FINALIZED_COUNTER.labels(status="superseded", kind=run.backfill_kind).inc()
        else:
            # We hold the run row's FOR UPDATE lock, so a missed CAS can only mean our own
            # readiness stamp superseded a cohort-scoped run inside this transaction —
            # the run is terminal (superseded + finished_at) and counted as such. That reads the
            # one-participation invariant checked above: with more, a run that also stamped a cohort
            # would land here and be counted purely superseded.
            result.superseded += 1
            RUNS_FINALIZED_COUNTER.labels(status="superseded", kind=run.backfill_kind).inc()

        # Re-fire invalidation when completing a run whose stamps landed in an earlier pass, covering
        # a crash between that pass's commit and its post-commit invalidation. (A crash after this
        # terminal transition commits leaves any staleness bounded by the flags-cache verifier task
        # and the behavioral-ids cache TTL, in the fail-closed direction.)
        if terminal_status == CohortBackfillRunStatus.COMPLETED and stamped >= 1:
            invalidate_team = True

    return invalidate_team
