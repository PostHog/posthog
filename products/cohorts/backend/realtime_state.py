"""The one realtime state a cohort shows a reader, derived from the pipeline's several truths.

Django's ``is_flag_compatible``, the backfill run row, and the realtime team allowlist each answer a
different question, and none of them is the answer a person wants ("can a feature flag target this
cohort right now"). This module collapses them into one state plus, while the cohort is being
prepared, that build's progress.

Only cohorts with event-based criteria get a state. Feature flags could always target the rest, and
the flag API never checks them against the backfill stamps, so a person-only cohort with no stamp
would read as not targetable when it is.

Every state comes from a row that exists. A cohort whose backfill was refused, lost, or never
triggered has no run, so it reads as ``needs_attention`` and never as ``building``: the filters
changing is not evidence that anything is rebuilding.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import models
from django.db.models import Count, Max, Q

import structlog

from posthog.dataclasses import frozen
from posthog.redis import get_client as get_redis_client

from products.cohorts.backend.models.backfill import (
    ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
    CohortBackfillChunk,
    CohortBackfillChunkStatus,
    CohortBackfillKind,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillTrigger,
)
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.dependencies import cohort_backfill_pending_key
from products.cohorts.backend.realtime_teams import is_realtime_cohort_team

logger = structlog.get_logger(__name__)


class CohortRealtimeState(models.TextChoices):
    STATIC = "static", "Static"
    DAILY = "daily", "Daily"
    BUILDING = "building", "Building"
    REBUILDING = "rebuilding", "Rebuilding"
    READY = "ready", "Ready"
    NEEDS_ATTENTION = "needs_attention", "Needs attention"


class CohortHistoryBuildPhase(models.TextChoices):
    WAITING = "waiting", "Waiting"
    SCANNING = "scanning", "Scanning"
    CHECKING = "checking", "Checking"


# The run statuses a build shows a phase for. `blocked` is active but parked on an operator
# attestation, and every terminal status is either done or a failure, so both resolve to a state
# instead. Exhaustive on purpose: a ninth run status has to be placed here deliberately rather than
# fall through to a phase that would misdescribe it.
_PHASE_BY_RUN_STATUS: dict[str, CohortHistoryBuildPhase] = {
    CohortBackfillRunStatus.AWAITING_BOUNDARY: CohortHistoryBuildPhase.WAITING,
    CohortBackfillRunStatus.SEEDING: CohortHistoryBuildPhase.SCANNING,
    CohortBackfillRunStatus.RECONCILING: CohortHistoryBuildPhase.CHECKING,
}

# Least to most advanced. A cohort waiting on two kinds is only as far along as its slowest one.
_PHASE_RANK: dict[str, int] = {
    CohortHistoryBuildPhase.WAITING: 0,
    CohortHistoryBuildPhase.SCANNING: 1,
    CohortHistoryBuildPhase.CHECKING: 2,
}


@frozen
class CohortHistoryBuild:
    """The run building one cohort's history, as much of it as a reader needs."""

    phase: str
    percent_complete: int | None
    updated_at: datetime | None


@frozen
class CohortRealtimeReadiness:
    """What one cohort can be used for right now."""

    state: str
    ready_at: datetime | None
    build: CohortHistoryBuild | None


def _settled_state(cohort: Cohort) -> str | None:
    """The state a cohort has without consulting a run row, or None when a run decides it."""
    if cohort.is_static:
        return CohortRealtimeState.STATIC
    if cohort.cohort_type != CohortType.REALTIME:
        return CohortRealtimeState.DAILY
    if cohort.is_flag_compatible:
        return CohortRealtimeState.READY
    return None


def _required_backfill_kinds(cohort: Cohort) -> set[str]:
    """The backfill kinds this cohort's current filters need stamped before flags can target it.

    The same two predicates `is_flag_compatible` gates on. A cohort can still be participating in
    an active run for a kind its filters no longer use, and that run decides nothing about it.
    """
    kinds = {CohortBackfillKind.BEHAVIORAL.value} if cohort._has_filter_type("behavioral") else set()
    if cohort._has_filter_type("person") or cohort._has_filter_type("person_metadata"):
        kinds.add(CohortBackfillKind.PERSON_PROPERTY.value)
    return kinds


def _percent_complete(chunks: dict[str, Any] | None) -> int | None:
    """Scan progress as a whole percent, or None while the run has planned no chunks."""
    if not chunks or not chunks["chunks_total"]:
        return None
    return round(chunks["chunks_confirmed"] / chunks["chunks_total"] * 100)


def _active_participations_per_cohort(
    team_id: int, cohort_ids: Sequence[int], *, statuses: Iterable[str]
) -> dict[int, list[CohortBackfillRunCohort]]:
    """Every live participation per cohort among ``statuses``, newest run first.

    Participations are the per-cohort lens: a team-scoped run carries no ``cohort_id`` of its own,
    so reading runs directly would miss every cohort a team enablement run is building.

    A superseded participation is dropped even though its run is still active. Editing a cohort
    that a team run is building supersedes only its participation, and reading that row would
    report the abandoned build instead of the rebuild the edit just asked for.

    One cohort can hold several at once, one per backfill kind, so the caller combines them rather
    than taking the newest: a cohort is ready only once every kind it needs has finished.
    """
    participations = (
        # `Cohort` is a RootTeamMixin, so a cohort's team id is already the project's canonical
        # team: resolving it again would put a `posthog_team` read on every cohort request.
        CohortBackfillRunCohort.objects.for_team(team_id, canonical=True)
        .filter(cohort_id__in=cohort_ids, superseded_at__isnull=True, run__status__in=statuses)
        .select_related("run")
        # Both rows carry JSON columns wide enough to dwarf the request: the run's `pinned` holds
        # the catalog of every cohort it is building, and a page repeats that row per cohort.
        .only(
            "cohort_id",
            "run__status",
            "run__trigger_kind",
            "run__backfill_kind",
            "run__created_at",
            "run__updated_at",
        )
        .order_by("cohort_id", "-run__created_at")
    )
    by_cohort: dict[int, list[CohortBackfillRunCohort]] = defaultdict(list)
    for participation in participations:
        by_cohort[participation.cohort_id].append(participation)
    return by_cohort


def _queued_trigger_kinds(cohort_ids: Sequence[int]) -> dict[int, str] | None:
    """The trigger kind of each cohort's debounced run-creation task, for the cohorts that have one.

    A save enqueues that task with a five-minute countdown, so for those five minutes the debounce
    key is the only record that a build was asked for. Without it, every cohort would read as
    `needs_attention` for the first five minutes after the edit that is about to rebuild it.

    Returns None when the lookup itself failed, which is not the same answer as "no task is
    queued": the caller reports no state at all rather than asserting that nothing is preparing
    these cohorts.
    """
    keys = [
        cohort_backfill_pending_key(cohort_id, kind) for cohort_id in cohort_ids for kind in CohortBackfillKind.values
    ]
    try:
        values = get_redis_client().mget(keys)
    except Exception as error:
        # Saying nothing is a better failure than a wrong state, and than a cohort list that 500s.
        logger.warning("cohort_backfill_pending_lookup_failed", error=str(error))
        return None

    queued: dict[int, str] = {}
    for key, value in zip(keys, values, strict=True):
        if value is None:
            continue
        cohort_id = int(key.rsplit(":", 1)[1])
        # Any kind's task counts as a build being on its way, and an edit outranks a creation:
        # both kinds are enqueued together, and the edit is the one with a consequence for flags.
        trigger = value.decode() if isinstance(value, bytes) else str(value)
        if queued.get(cohort_id) != CohortBackfillTrigger.COHORT_EDITED:
            queued[cohort_id] = trigger
    return queued


def _chunk_tallies(team_id: int, run_ids: Sequence[UUID]) -> dict[UUID, dict[str, Any]]:
    if not run_ids:
        return {}
    tallies = (
        CohortBackfillChunk.objects.for_team(team_id, canonical=True)
        .filter(run_id__in=run_ids)
        .values("run_id")
        .annotate(
            chunks_total=Count("id"),
            chunks_confirmed=Count("id", filter=Q(status=CohortBackfillChunkStatus.CONFIRMED)),
            # A chunk finishing does not touch the run row, so the run's own `updated_at` can sit
            # still for hours while the percentage climbs.
            chunks_updated_at=Max("updated_at"),
        )
    )
    return {tally["run_id"]: tally for tally in tallies}


def _required_participations(
    participations: Sequence[CohortBackfillRunCohort], required_kinds: set[str]
) -> list[CohortBackfillRunCohort]:
    """The live participations for the backfill kinds a cohort's current filters still need."""
    return [participation for participation in participations if participation.run.backfill_kind in required_kinds]


def _deciding_participation(required: Sequence[CohortBackfillRunCohort]) -> CohortBackfillRunCohort | None:
    """The participation whose run describes the cohort's build, or None when no run does.

    A cohort needing both kinds is waiting on both, so the least advanced one is what a reader
    should see. A run parked on an operator (`blocked`) has no phase, and a build one kind cannot
    leave is not in progress, so that case reports no run at all and the cohort resolves to
    `needs_attention`.
    """
    if not required or any(participation.run.status not in _PHASE_BY_RUN_STATUS for participation in required):
        return None
    return min(required, key=lambda participation: _PHASE_RANK[_PHASE_BY_RUN_STATUS[participation.run.status]])


def _resolve_for_team(team_id: int, cohorts: Sequence[Cohort]) -> dict[int, CohortRealtimeReadiness]:
    readiness: dict[int, CohortRealtimeReadiness] = {}
    pending: list[Cohort] = []

    for cohort in cohorts:
        settled = _settled_state(cohort)
        if settled is None:
            pending.append(cohort)
        else:
            readiness[cohort.id] = CohortRealtimeReadiness(state=settled, ready_at=cohort.realtime_ready_at, build=None)

    if not pending:
        return readiness

    active = _active_participations_per_cohort(
        team_id, [cohort.id for cohort in pending], statuses=ACTIVE_COHORT_BACKFILL_RUN_STATUSES
    )
    required = {
        cohort.id: _required_participations(active.get(cohort.id, []), _required_backfill_kinds(cohort))
        for cohort in pending
    }
    building = {
        cohort.id: participation
        for cohort in pending
        if (participation := _deciding_participation(required[cohort.id]))
    }
    chunks_by_run = _chunk_tallies(team_id, [participation.run_id for participation in building.values()])
    queued = _queued_trigger_kinds([cohort.id for cohort in pending if cohort.id not in building])

    for cohort in pending:
        participation = building.get(cohort.id)
        if participation is not None:
            run = participation.run
            chunks = chunks_by_run.get(run.id)
            chunks_updated_at = chunks["chunks_updated_at"] if chunks else None
            # Any required kind's run being an edit makes this a rebuild, the same way the queued
            # path ranks an edit above a creation.
            trigger = (
                CohortBackfillTrigger.COHORT_EDITED
                if any(other.run.trigger_kind == CohortBackfillTrigger.COHORT_EDITED for other in required[cohort.id])
                else run.trigger_kind
            )
            build = CohortHistoryBuild(
                phase=_PHASE_BY_RUN_STATUS[run.status],
                percent_complete=_percent_complete(chunks),
                updated_at=max(run.updated_at, chunks_updated_at) if chunks_updated_at else run.updated_at,
            )
        elif queued is None:
            # The lookup that would say whether a build is queued is unavailable, so this cohort
            # gets no state rather than one asserting that nothing is preparing it.
            continue
        elif cohort.id in queued:
            trigger = queued[cohort.id]
            build = CohortHistoryBuild(phase=CohortHistoryBuildPhase.WAITING, percent_complete=None, updated_at=None)
        else:
            readiness[cohort.id] = CohortRealtimeReadiness(
                state=CohortRealtimeState.NEEDS_ATTENTION, ready_at=None, build=None
            )
            continue

        readiness[cohort.id] = CohortRealtimeReadiness(
            state=(
                CohortRealtimeState.REBUILDING
                if trigger == CohortBackfillTrigger.COHORT_EDITED
                else CohortRealtimeState.BUILDING
            ),
            ready_at=None,
            build=build,
        )

    return readiness


def has_realtime_state(cohort: Cohort) -> bool:
    """Whether the realtime trait can change anything about this cohort.

    False for cohorts on a team that does not run the pipeline, because their flags can never read
    realtime membership; and for cohorts with no event-based criteria, because flags could always
    target those and the flag API does not gate them on a backfill. Neither has a realtime story to
    tell, so neither pays for the run lookups, or the rollout flag evaluation, that telling it costs.

    In-memory only: the allowlist is a parsed setting and the filter types come off the cohort row.
    """
    return cohort.pk is not None and is_realtime_cohort_team(cohort.team_id) and cohort._has_filter_type("behavioral")


def resolve_realtime_readiness(cohorts: Sequence[Cohort]) -> dict[int, CohortRealtimeReadiness]:
    """One readiness per cohort id, for the cohorts ``has_realtime_state`` admits."""
    by_team: dict[int, list[Cohort]] = defaultdict(list)
    for cohort in cohorts:
        if has_realtime_state(cohort):
            by_team[cohort.team_id].append(cohort)

    readiness: dict[int, CohortRealtimeReadiness] = {}
    for team_id, team_cohorts in by_team.items():
        readiness.update(_resolve_for_team(team_id, team_cohorts))
    return readiness
