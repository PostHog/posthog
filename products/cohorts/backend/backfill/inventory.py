"""Classifies active backfill runs so an operator can drain the wedged ones.

An active run is not just work in progress: it holds one of the partial uniqueness slots
(``cohort_bfr_active_cohort_kind_uq``, ``cohort_bfr_active_team_kind_uq``), so a run that can never
reach a terminal status blocks its cohort or team from ever backfilling again. Nothing today can tell
those apart from a run that is simply slow, and `observe.py`'s gauges count runs per status without
saying which ones are stuck.

Every run gets exactly one classification answering *what is it waiting on*. Age is a filter callers
compose on top rather than a bucket of its own, so ``finalizable`` stays a byte-for-byte mirror of the
finalizer's discovery predicate: the operator's verified list has to be exactly the set the finalizer
will stamp, and a "stale" bucket would swallow old runs out of every other bucket.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Literal, get_args
from uuid import UUID

from django.conf import settings
from django.db.models import Count, Max, Q
from django.utils import timezone as django_timezone

from posthog.dataclasses import frozen

from products.cohorts.backend.backfill.allowlist import parse_run_allowlist
from products.cohorts.backend.models.backfill import (
    ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
    CohortBackfillChunk,
    CohortBackfillChunkStatus,
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunStatus,
    CohortBackfillScope,
)

# The chunk tallies a run needs when it has no chunk rows yet: the grouped chunk query below only
# emits a row per run that has chunks, so runs missing from it fall back to these zeros.
_EMPTY_CHUNK_TALLY: dict[str, Any] = {
    "chunks_total": 0,
    "chunks_confirmed": 0,
    "chunks_failed_exhausted": 0,
    "chunk_last_progress_at": None,
}

RunClassification = Literal[
    "orphaned",
    "finalizable",
    "awaiting-observation",
    "seeding-stalled",
    "seeding-healthy",
    "blocked",
    "awaiting-boundary",
]

RUN_CLASSIFICATIONS: tuple[RunClassification, ...] = get_args(RunClassification)

# Classifications a `terminalize` sweep may cancel without extra opt-in. `seeding-stalled` and
# `orphaned` are the two that can never reach a terminal status on their own; the rest are either
# legitimately parked (`blocked`, `awaiting-boundary` — targetable, but only alongside an age cutoff)
# or still owned by the seeder.
DEFAULT_TERMINALIZE_CLASSIFICATIONS: tuple[RunClassification, ...] = ("seeding-stalled", "orphaned")

# Only meaningful together with an age cutoff: these are parked by design, not broken.
AGE_GATED_TERMINALIZE_CLASSIFICATIONS: tuple[RunClassification, ...] = ("blocked", "awaiting-boundary")

# Runs the seeder is still working: one is scanning chunks, the other is waiting to be observed.
# Canceling either races a live worker instead of freeing a stuck slot, and it discards seeding
# progress the run would otherwise finish, so it takes an explicit opt-in. `finalizable` needs its
# own opt-in for the mirror-image reason: that work is already *done*.
SEEDER_OWNED_CLASSIFICATIONS: tuple[RunClassification, ...] = ("awaiting-observation", "seeding-healthy")

# Mirrors `SEEDER_MAX_CHUNK_ATTEMPTS`'s envconfig default (rust/cohort-seeder/src/config.rs). Django
# cannot read the seeder's config, so this is a knob on the command rather than a shared setting.
DEFAULT_MAX_CHUNK_ATTEMPTS = 5


@frozen
class RunFacts:
    """Everything ``classify_run`` reads.

    Plain values only: no ORM object reaches the classifier, so the predicates are unit-testable
    without a database and cannot accidentally issue a query per run.
    """

    status: str
    scope: str
    cohort_id: int | None
    participations_total: int
    participations_open: int
    live_participation_cohorts: int
    reconcile_observed_at: datetime | None
    boundary_established_at: datetime | None
    chunks_planned_at: datetime | None
    chunks_total: int
    chunks_unconfirmed: int
    chunks_failed_exhausted: int
    chunk_last_progress_at: datetime | None
    now: datetime
    stalled_after: timedelta


@frozen
class RunInventoryRow:
    run_id: UUID
    team_id: int
    backfill_kind: str
    scope: str
    status: str
    trigger_kind: str
    cohort_id: int | None
    classification: RunClassification
    finalizer_gated: bool
    allowlisted: bool
    created_at: datetime
    updated_at: datetime
    reconcile_observed_at: datetime | None
    participations_total: int
    participations_open: int
    participations_stamped: int
    participations_superseded: int
    chunks_total: int
    chunks_confirmed: int
    chunks_failed_exhausted: int
    chunk_last_progress_at: datetime | None
    evidence: str
    blocked_reason: str
    error: str


def classify_run(facts: RunFacts) -> RunClassification:
    """The single bucket a run belongs to. Raises on a terminal status: callers filter to active."""
    if facts.status not in ACTIVE_COHORT_BACKFILL_RUN_STATUSES:
        raise ValueError(f"{facts.status} is not an active backfill run status")

    if _orphan_evidence(facts):
        return "orphaned"

    if facts.status == CohortBackfillRunStatus.RECONCILING:
        return "finalizable" if facts.reconcile_observed_at is not None else "awaiting-observation"

    if facts.status == CohortBackfillRunStatus.SEEDING:
        return "seeding-stalled" if _stall_evidence(facts) else "seeding-healthy"

    if facts.status == CohortBackfillRunStatus.BLOCKED:
        return "blocked"

    return "awaiting-boundary"


def classification_evidence(facts: RunFacts) -> str:
    """Why a run reads as orphaned or stalled, for the operator deciding whether to cancel it."""
    return _orphan_evidence(facts) or _stall_evidence(facts) or ""


def _orphan_evidence(facts: RunFacts) -> str:
    """An orphan can never finalize regardless of status, so this precedes the status buckets."""
    if facts.scope == CohortBackfillScope.COHORT and facts.cohort_id is None:
        # The run's FK is SET_NULL, so a hard-deleted cohort leaves a cohort-scoped run pointing at
        # nothing to stamp.
        return "cohort-scoped run whose cohort was hard-deleted"
    if facts.participations_total == 0:
        # Participations CASCADE on Cohort, so a hard delete takes them with it.
        return "no participation rows left"
    if facts.live_participation_cohorts == 0:
        return "every participating cohort is deleted"
    if facts.participations_open == 0:
        # `record_participation_partial` supersedes a participation while leaving the run active, so
        # a run can hold its uniqueness slot with no work left to do.
        return "every participation already resolved"
    return ""


def _stall_evidence(facts: RunFacts) -> str:
    """Why a seeding run cannot make progress. Empty means it still can."""
    if facts.chunks_failed_exhausted:
        # Provably unclaimable, not a heuristic: `claim_next` only claims a pending/failed chunk with
        # `attempts < max`, and the run's CAS out of `seeding` requires every chunk confirmed. Such a
        # run stays in `seeding` forever.
        return f"{facts.chunks_failed_exhausted} chunk(s) failed at the attempt cap with an expired lease"

    cutoff = facts.now - facts.stalled_after
    if facts.chunks_planned_at is None:
        if facts.boundary_established_at is not None and facts.boundary_established_at < cutoff:
            return "boundary established but no chunks planned"
        return ""

    if facts.chunks_total == 0:
        # A run whose conditions plan no days legitimately stamps `chunks_planned_at` with zero
        # chunks and waits for the completion sweep, so this only reads as stalled once that sweep
        # has had time to run.
        if facts.chunks_planned_at < cutoff:
            return "chunks planned but none exist"
        return ""
    if facts.chunks_unconfirmed and (facts.chunk_last_progress_at is None or facts.chunk_last_progress_at < cutoff):
        return f"{facts.chunks_unconfirmed} unconfirmed chunk(s) with no progress since the cutoff"
    return ""


def collect_run_inventory(
    *,
    team_id: int | None = None,
    kinds: Sequence[str] | None = None,
    statuses: Sequence[str] | None = None,
    classifications: Sequence[RunClassification] | None = None,
    run_ids: Sequence[UUID] | None = None,
    stalled_after: timedelta,
    older_than: timedelta | None = None,
    max_chunk_attempts: int = DEFAULT_MAX_CHUNK_ATTEMPTS,
    now: datetime | None = None,
) -> list[RunInventoryRow]:
    """Every active run matching the filters, classified, oldest first.

    The scan is cross-team on purpose, like the finalizer's own discovery: the verified list has to
    cover every team the finalizer will stamp, and a per-team read would silently produce a subset.
    """
    now = now or django_timezone.now()
    allowlist = parse_run_allowlist(settings.BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST)
    person_readiness_off = not settings.BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED

    queryset = CohortBackfillRun.objects.unscoped().filter(status__in=statuses or ACTIVE_COHORT_BACKFILL_RUN_STATUSES)
    if team_id is not None:
        queryset = queryset.filter(team_id=team_id)
    if kinds:
        queryset = queryset.filter(backfill_kind__in=kinds)
    if run_ids:
        queryset = queryset.filter(id__in=run_ids)
    if older_than is not None:
        queryset = queryset.filter(created_at__lt=now - older_than)

    # Annotate the per-run tallies rather than walking the relations: the prod active set is
    # dominated by blocked runs, and an N+1 here makes the command unusable mid-cleanup. Only the
    # participation aggregates are joined here; the chunk aggregates come from a separate grouped
    # query below, because joining both `run_cohorts` and `chunks` in one SELECT multiplies into
    # one intermediate row per participation-chunk pair, which a large team run turns into a heavy
    # sort even though `distinct=True` keeps the counts right.
    runs = list(
        queryset.annotate(
            participations_total=Count("run_cohorts", distinct=True),
            participations_stamped=Count("run_cohorts", filter=Q(run_cohorts__stamped_at__isnull=False), distinct=True),
            participations_superseded=Count(
                "run_cohorts", filter=Q(run_cohorts__superseded_at__isnull=False), distinct=True
            ),
            live_participation_cohorts=Count(
                "run_cohorts", filter=Q(run_cohorts__cohort__deleted=False), distinct=True
            ),
        ).order_by("created_at")
    )

    # One relation per query, so each aggregate stays linear in the chunk count. Keyed by run id and
    # merged back below; runs with no chunks are simply absent and fall back to `_EMPTY_CHUNK_TALLY`.
    chunk_tallies = (
        CohortBackfillChunk.objects.unscoped()
        .filter(run_id__in=[run.id for run in runs])
        .values("run_id")
        .annotate(
            chunks_total=Count("id"),
            chunks_confirmed=Count("id", filter=Q(status=CohortBackfillChunkStatus.CONFIRMED)),
            chunks_failed_exhausted=Count(
                "id",
                filter=Q(status=CohortBackfillChunkStatus.FAILED, attempts__gte=max_chunk_attempts)
                & (Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lt=now)),
            ),
            chunk_last_progress_at=Max("updated_at"),
        )
    )
    chunks_by_run = {tally["run_id"]: tally for tally in chunk_tallies}

    inventory: list[RunInventoryRow] = []
    for run in runs:
        chunks = chunks_by_run.get(run.id, _EMPTY_CHUNK_TALLY)
        facts = RunFacts(
            status=run.status,
            scope=run.scope,
            cohort_id=run.cohort_id,
            participations_total=run.participations_total,
            participations_open=run.participations_total - run.participations_superseded,
            live_participation_cohorts=run.live_participation_cohorts,
            reconcile_observed_at=run.reconcile_observed_at,
            boundary_established_at=run.boundary_established_at,
            chunks_planned_at=run.chunks_planned_at,
            chunks_total=chunks["chunks_total"],
            chunks_unconfirmed=chunks["chunks_total"] - chunks["chunks_confirmed"],
            chunks_failed_exhausted=chunks["chunks_failed_exhausted"],
            chunk_last_progress_at=chunks["chunk_last_progress_at"],
            now=now,
            stalled_after=stalled_after,
        )
        classification = classify_run(facts)
        if classifications and classification not in classifications:
            continue
        inventory.append(
            RunInventoryRow(
                run_id=run.id,
                team_id=run.team_id,
                backfill_kind=run.backfill_kind,
                scope=run.scope,
                status=run.status,
                trigger_kind=run.trigger_kind,
                cohort_id=run.cohort_id,
                classification=classification,
                finalizer_gated=person_readiness_off and run.backfill_kind == CohortBackfillKind.PERSON_PROPERTY,
                allowlisted=allowlist is None or run.id in allowlist,
                created_at=run.created_at,
                updated_at=run.updated_at,
                reconcile_observed_at=run.reconcile_observed_at,
                participations_total=facts.participations_total,
                participations_open=facts.participations_open,
                participations_stamped=run.participations_stamped,
                participations_superseded=run.participations_superseded,
                chunks_total=facts.chunks_total,
                chunks_confirmed=chunks["chunks_confirmed"],
                chunks_failed_exhausted=facts.chunks_failed_exhausted,
                chunk_last_progress_at=facts.chunk_last_progress_at,
                evidence=classification_evidence(facts),
                blocked_reason=run.blocked_reason,
                error=run.error,
            )
        )
    return inventory


def summarize_inventory(rows: Sequence[RunInventoryRow]) -> dict[RunClassification, int]:
    """Counts per classification, every bucket present so a drained one reads as 0, not absent."""
    summary: dict[RunClassification, int] = dict.fromkeys(RUN_CLASSIFICATIONS, 0)
    for row in rows:
        summary[row.classification] += 1
    return summary


def stampable_now(rows: Sequence[RunInventoryRow]) -> list[RunInventoryRow]:
    """The runs the finalizer would stamp the moment it is enabled, oldest observation first.

    Excludes runs held by the person readiness gate: they are ``finalizable`` by column but invisible
    to the finalizer's kind filter, so verifying one now and putting it on the allowlist would stamp
    it much later, whenever that gate opens.
    """
    stampable = [row for row in rows if row.classification == "finalizable" and not row.finalizer_gated]
    # `reconcile_observed_at` is non-null for every `finalizable` row; the fallback keeps mypy honest.
    return sorted(stampable, key=lambda row: row.reconcile_observed_at or row.created_at)


def allowlist_env_line(rows: Sequence[RunInventoryRow]) -> str:
    """The paste-ready allowlist line for the runs above.

    Emits ``none`` rather than an empty value when there is nothing to stamp: an empty value is read
    as "every run", which is the opposite of what an operator who found no verified runs means.
    """
    run_ids = ",".join(str(row.run_id) for row in rows)
    return f"BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST={run_ids or 'none'}"
