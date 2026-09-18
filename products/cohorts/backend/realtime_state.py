"""The one realtime state a cohort shows a reader, derived from the pipeline's several truths.

Django's ``is_flag_compatible``, the backfill run row, and the realtime team allowlist each answer a
different question, and none of them is the answer a person wants ("can a feature flag target this
cohort right now"). This module collapses them into one state plus, while the cohort is being
prepared, that build's progress.

Only a cohort whose criteria decide the answer gets a state: one with event-based criteria, which
a backfill has to prepare before flags can read it, and one that matches on person properties,
which flags read straight off the person and can therefore always target. A cohort with neither
gets no state, so nothing claims an answer the flag API does not enforce.

Every state comes from a row that exists, and from one per backfill kind the cohort needs. A kind
whose backfill was refused, lost, or never triggered has no run and no queued task, so the cohort
reads as ``needs_attention`` and never as ``building``, however well its other kind is going: the
filters changing is not evidence that anything is rebuilding.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, TypeGuard
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
    CohortBackfillRun,
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
    PERSON_PROPERTIES = "person_properties", "Person properties"
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


def _has_phase(run: CohortBackfillRun | None) -> TypeGuard[CohortBackfillRun]:
    """Whether a live run is far enough along to describe a build phase."""
    return run is not None and run.status in _PHASE_BY_RUN_STATUS


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


def _has_event_criteria(cohort: Cohort) -> bool:
    """Whether the cohort matches on events, counting the ones that store that in ``groups``.

    ``_has_filter_type`` walks the ``filters`` JSON alone, and a legacy cohort keeps its condition
    in the deprecated ``groups`` field instead, where ``Cohort.properties`` is what turns an
    ``action_id`` or ``event_id`` entry into a behavioral property. The flag API refuses a cohort
    on either signal, so both have to reach this module as well, or such a cohort would read as one
    flags can target and then be refused on save. ``groups`` is only parsed when ``filters`` is
    empty, which is the one case ``Cohort.properties`` reads it at all, so a modern cohort pays
    nothing for the second test.
    """
    if cohort._has_filter_type("behavioral"):
        return True
    return not cohort.filters and any(prop.type == "behavioral" for prop in cohort.properties.flat)


def _has_person_criteria(cohort: Cohort) -> bool:
    """Whether the cohort matches on person properties, which feature flags read directly."""
    return cohort._has_filter_type("person") or cohort._has_filter_type("person_metadata")


def _settled_state(cohort: Cohort) -> str | None:
    """The state a cohort has without consulting a run row, or None when a run decides it."""
    if cohort.is_static:
        return CohortRealtimeState.STATIC
    if not _has_event_criteria(cohort):
        # Flags evaluate person properties off the person record as they run, so they can target
        # this cohort whatever the pipeline is doing. Only an event-based leaf waits on a backfill.
        return CohortRealtimeState.PERSON_PROPERTIES
    if cohort.cohort_type != CohortType.REALTIME:
        return CohortRealtimeState.DAILY
    if cohort.is_flag_compatible:
        return CohortRealtimeState.READY
    return None


def _required_backfill_kinds(cohort: Cohort) -> set[str]:
    """The backfill kinds this cohort's current filters need stamped before flags can target it.

    The same mapping `is_flag_compatible` gates on. A cohort can still be participating in an
    active run for a kind its filters no longer use, and that run decides nothing about it.
    """
    return set(cohort._required_backfill_stamps())


def _percent_complete(chunks: dict[str, Any] | None) -> int | None:
    """Scan progress as a whole percent, or None while the run has planned no chunks.

    Rounded down, so 100 means every chunk is confirmed rather than 199 of 200.
    """
    if not chunks or not chunks["chunks_total"]:
        return None
    return chunks["chunks_confirmed"] * 100 // chunks["chunks_total"]


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


def _queued_triggers(pairs: Sequence[tuple[int, str]]) -> dict[tuple[int, str], str] | None:
    """The trigger kind of the debounced run-creation task for each cohort and backfill kind asked for.

    A save enqueues that task with a five-minute countdown, so for those five minutes the debounce
    key is the only record that a build was asked for. Without it, every cohort would read as
    `needs_attention` for the first five minutes after the edit that is about to rebuild it.

    Returns None when the lookup itself failed, which is not the same answer as "no task is
    queued": the caller reports no state at all rather than asserting that nothing is preparing
    these cohorts.
    """
    if not pairs:
        # redis-py sends an argument-less MGET rather than short-circuiting, and the server
        # answers with an error that `parse_response` turns into an empty list. Every build that
        # is already running takes this path, and that is when the detail endpoint is polled.
        return {}

    keys = [cohort_backfill_pending_key(cohort_id, kind) for cohort_id, kind in pairs]
    try:
        values = get_redis_client().mget(keys)
    except Exception as error:
        # Saying nothing is a better failure than a wrong state, and than a cohort list that 500s.
        logger.warning("cohort_backfill_pending_lookup_failed", error=str(error))
        return None

    return {
        pair: (value.decode() if isinstance(value, bytes) else str(value))
        for pair, value in zip(pairs, values, strict=True)
        if value is not None
    }


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


@frozen
class _KindProgress:
    """How one backfill kind of one cohort is coming along, from a run row or from a queued task."""

    phase: str
    trigger: str
    run: CohortBackfillRun | None


def _live_run_per_kind(
    participations: Sequence[CohortBackfillRunCohort], required_kinds: set[str]
) -> dict[str, CohortBackfillRun]:
    """The newest live run per backfill kind, among the kinds a cohort's current filters still need.

    A cohort can hold two live participations of one kind at once, its own run and the team's, and
    it can hold participations for a kind its filters no longer use, which decide nothing about it.
    """
    per_kind: dict[str, CohortBackfillRun] = {}
    for participation in participations:  # newest run first
        kind = participation.run.backfill_kind
        if kind in required_kinds and kind not in per_kind:
            per_kind[kind] = participation.run
    return per_kind


def _cohort_progress(
    cohort_id: int,
    required_kinds: set[str],
    live_runs: dict[str, CohortBackfillRun],
    queued: dict[tuple[int, str], str],
) -> list[_KindProgress] | None:
    """One progress record per required backfill kind, or None when nothing is building the cohort.

    A cohort is ready only once every kind its filters need has finished, so every one of them has
    to be moving for the cohort to read as a build in progress. One kind seeding while the other
    was refused, lost or never triggered is a cohort nothing is carrying to ready, and reporting it
    as preparing would leave a progress bar running against a build that is not coming.

    A run that has started outranks the debounce key for its kind: the key survives until the
    countdown it was set for expires, so both records exist for as long as the task takes to run.
    """
    progress: list[_KindProgress] = []
    for kind in sorted(required_kinds):
        run = live_runs.get(kind)
        if _has_phase(run):
            progress.append(_KindProgress(phase=_PHASE_BY_RUN_STATUS[run.status], trigger=run.trigger_kind, run=run))
            continue
        trigger = queued.get((cohort_id, kind))
        if trigger is None:
            return None
        progress.append(_KindProgress(phase=CohortHistoryBuildPhase.WAITING, trigger=trigger, run=None))
    return progress or None


def _resolve_for_team(team_id: int, cohorts: Sequence[Cohort]) -> dict[int, CohortRealtimeReadiness]:
    readiness: dict[int, CohortRealtimeReadiness] = {}
    pending: list[Cohort] = []

    for cohort in cohorts:
        settled = _settled_state(cohort)
        if settled is None:
            pending.append(cohort)
        else:
            readiness[cohort.id] = CohortRealtimeReadiness(
                # Only a prepared realtime cohort has a moment it became targetable. A person
                # property cohort always was, and it can carry a stamp from an earlier definition.
                state=settled,
                ready_at=cohort.realtime_ready_at if settled == CohortRealtimeState.READY else None,
                build=None,
            )

    if not pending:
        return readiness

    participations = _active_participations_per_cohort(
        team_id, [cohort.id for cohort in pending], statuses=ACTIVE_COHORT_BACKFILL_RUN_STATUSES
    )
    required_kinds = {cohort.id: _required_backfill_kinds(cohort) for cohort in pending}
    live_runs = {
        cohort.id: _live_run_per_kind(participations.get(cohort.id, []), required_kinds[cohort.id])
        for cohort in pending
    }

    # A kind whose live run has a phase is progressing on its own evidence. Every other required
    # kind has to be found in the debounce key: a run parked on an operator (`blocked`) has no
    # phase, and a kind with no live run at all may still have a task waiting out its countdown.
    # Asking about nothing else keeps a page whose builds are all running free of a round trip.
    unresolved = {
        cohort.id: {kind for kind in required_kinds[cohort.id] if not _has_phase(live_runs[cohort.id].get(kind))}
        for cohort in pending
    }
    queued = _queued_triggers([(cohort.id, kind) for cohort in pending for kind in sorted(unresolved[cohort.id])])

    progress_by_cohort: dict[int, list[_KindProgress]] = {}
    for cohort in pending:
        if queued is None and unresolved[cohort.id]:
            # The lookup that would say whether a build is queued is unavailable, so this cohort
            # gets no state rather than one asserting that nothing is preparing it.
            continue
        progress = _cohort_progress(cohort.id, required_kinds[cohort.id], live_runs[cohort.id], queued or {})
        if progress is None:
            readiness[cohort.id] = CohortRealtimeReadiness(
                state=CohortRealtimeState.NEEDS_ATTENTION, ready_at=None, build=None
            )
            continue
        progress_by_cohort[cohort.id] = progress

    # A cohort is only as far along as its least advanced kind, and that is the only run a reader
    # is shown, so it is the only one whose chunks are tallied.
    slowest_by_cohort = {
        cohort_id: min(progress, key=lambda item: _PHASE_RANK[item.phase])
        for cohort_id, progress in progress_by_cohort.items()
    }
    chunks_by_run = _chunk_tallies(
        team_id, [item.run.id for item in slowest_by_cohort.values() if item.run is not None]
    )

    for cohort_id, slowest in slowest_by_cohort.items():
        chunks = chunks_by_run.get(slowest.run.id) if slowest.run is not None else None
        timestamps = (
            slowest.run.updated_at if slowest.run is not None else None,
            chunks["chunks_updated_at"] if chunks else None,
        )
        readiness[cohort_id] = CohortRealtimeReadiness(
            state=(
                CohortRealtimeState.REBUILDING
                # Any required kind's build being an edit makes the whole thing a rebuild: both
                # kinds are asked for together, and the edit is the one with a consequence for flags.
                if any(
                    progress.trigger == CohortBackfillTrigger.COHORT_EDITED
                    for progress in progress_by_cohort[cohort_id]
                )
                else CohortRealtimeState.BUILDING
            ),
            ready_at=None,
            build=CohortHistoryBuild(
                phase=slowest.phase,
                # Chunks are the scan's own unit of work, so they measure no other phase: a
                # reconciling run has confirmed all of them, and a bar at 100% under "checking"
                # would read as a build that has finished and stalled.
                percent_complete=(
                    _percent_complete(chunks) if slowest.phase == CohortHistoryBuildPhase.SCANNING else None
                ),
                updated_at=max((stamp for stamp in timestamps if stamp is not None), default=None),
            ),
        )

    return readiness


def has_realtime_state(cohort: Cohort) -> bool:
    """Whether this cohort can have a flag targeting state at all.

    False on a team that does not run the pipeline, because its flags can never read realtime
    membership, and for a cohort whose criteria are neither event-based nor person properties: a
    cohort reference alone leaves the realtime evaluator no leaf to key membership on, and nothing
    in the flag API turns on it either. Neither has anything to say, so neither pays for the run
    lookups, or the rollout flag evaluation, that saying it costs.

    In-memory only: the allowlist is a parsed setting and the criteria come off the cohort row.
    """
    if cohort.pk is None or not is_realtime_cohort_team(cohort.team_id):
        return False
    return _has_event_criteria(cohort) or _has_person_criteria(cohort)


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
