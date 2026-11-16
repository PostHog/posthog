from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q

import structlog

from posthog.cohort_resave import CohortResaveStats, resave_team_cohorts, termination_unwinds
from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.cohorts.backend.backfill.finalize import refresh_readiness_caches
from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash
from products.cohorts.backend.backfill.runs import (
    INAPPLICABLE_BACKFILL_REASONS,
    BehavioralScanOverLimit,
    behavioral_backfill_ineligibility_reason,
    check_person_run_preconditions,
    create_person_team_backfill_run,
    create_team_backfill_run,
    person_backfill_ineligibility_reason,
)
from products.cohorts.backend.backfill.sizing import PersonSeedEstimateScanCapExceeded
from products.cohorts.backend.models.backfill import (
    ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunStatus,
    CohortBackfillScope,
    CohortBackfillTrigger,
)
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)
from products.cohorts.backend.realtime_teams import grant_realtime_cohort_access, grantable_access_rows

logger = structlog.get_logger(__name__)

_RESAVE_BATCH_SIZE = 500

# A team run that will seed, or has stamped readiness. A rerun after a refusal keeps it, so it does not
# seed that kind again or check it again against the scan limit. Not `blocked`, which the seeder never claims.
_KEPT_RUN_STATUSES = (
    CohortBackfillRunStatus.AWAITING_BOUNDARY,
    CohortBackfillRunStatus.SEEDING,
    CohortBackfillRunStatus.RECONCILING,
    CohortBackfillRunStatus.TRAILING,
    CohortBackfillRunStatus.COMPLETED,
)


@frozen
class RunCreated:
    run_id: UUID


@frozen
class RunAlreadyCreated:
    run_id: UUID


@frozen
class NothingToBackfill:
    pass


@frozen
class RunRefused:
    reason: str


@frozen
class RunFailed:
    reason: str


type RunOutcome = RunCreated | RunAlreadyCreated | NothingToBackfill | RunRefused | RunFailed


@frozen
class CohortRefusal:
    cohort_id: int
    kind: CohortBackfillKind
    reason: str


@frozen
class TeamEnablement:
    cleared_stamps: int
    resave: CohortResaveStats
    refused_cohorts: tuple[CohortRefusal, ...]
    behavioral: RunOutcome
    person: RunOutcome

    @property
    def promoted(self) -> bool:
        return not isinstance(self.behavioral, RunRefused | RunFailed) and not isinstance(
            self.person, RunRefused | RunFailed
        )


@frozen
class AlreadyServing:
    pass


def check_enablement(team_id: int, *, purpose: RealtimeCohortAccessPurpose) -> AlreadyServing | None:
    """Raises ``ValueError`` when `enable_realtime_cohorts` would refuse the team before it writes anything."""
    row = grantable_access_rows([team_id], purpose, RealtimeCohortTeamAccess.objects.all()).get(team_id)
    # Enabling goes through `processing`, which would hide a serving team's realtime state.
    if row is not None and row.level == RealtimeCohortLevel.SERVING:
        return AlreadyServing()
    # Without them neither team run can be created, so the team would only sit at `processing`.
    _, missing = check_person_run_preconditions()
    if missing:
        raise ValueError(f"Missing operator attestations: {', '.join(missing)}")
    if row is None:
        old_runs = list(
            CohortBackfillRun.objects.for_team(team_id)
            .filter(status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES)
            .values_list("id", flat=True)
        )
        if old_runs:
            raise ValueError(
                "Active backfill runs from before the grant, which can stamp the cohorts after enable clears them: "
                f"{', '.join(str(run_id) for run_id in old_runs)}. Cancel them with manage_cohort_backfill_runs "
                "terminalize --run-id, then run enable again."
            )
    return None


def enable_realtime_cohorts(team_id: int, *, purpose: RealtimeCohortAccessPurpose) -> TeamEnablement | AlreadyServing:
    """Put the team at `processing` with its cohorts ready for the pipeline, create its two team
    backfill runs, and promote it to `serving` only when neither run was refused.

    Raises ``ValueError`` before it writes anything for a team the grant refuses, when an operator
    attestation is missing, or when a first call finds an active backfill run. A first call clears the
    readiness stamps on the team's cohorts. A call after a refusal keeps the runs earlier calls created.
    """
    if (serving := check_enablement(team_id, purpose=purpose)) is not None:
        return serving
    has_row = RealtimeCohortTeamAccess.objects.filter(team_id=team_id).exists()
    cleared_stamps = 0 if has_row else _clear_unmaintained_stamps(team_id)

    team = Team.objects.get(id=team_id)
    with termination_unwinds() as coalesce_rebuilds:
        resave = resave_team_cohorts(
            team, batch_size=_RESAVE_BATCH_SIZE, dry_run=False, coalesce_rebuilds=coalesce_rebuilds
        )
    for cohort in _realtime_cohorts(team_id):
        ensure_filters_shape_hash(cohort)
    # After the resave and the hashes, because the processor loads the team's catalog within seconds of
    # the grant. A cohort that is stale or hash-less in that first load waits for the next refresh.
    grant_realtime_cohort_access(
        [team_id], level=RealtimeCohortLevel.PROCESSING, purpose=purpose, save_triggers_backfill=True
    )
    granted_at = RealtimeCohortTeamAccess.objects.get(team_id=team_id).processing_since
    assert granted_at is not None, "grant sets processing_since on the row it inserts"

    cohorts = _realtime_cohorts(team_id)
    behavioral_cohorts, behavioral_refusals = _judge(
        cohorts, CohortBackfillKind.BEHAVIORAL, behavioral_backfill_ineligibility_reason
    )
    person_cohorts, person_refusals = _judge(
        cohorts, CohortBackfillKind.PERSON_PROPERTY, person_backfill_ineligibility_reason
    )
    enablement = TeamEnablement(
        cleared_stamps=cleared_stamps,
        resave=resave,
        refused_cohorts=(*behavioral_refusals, *person_refusals),
        behavioral=_team_run(
            team_id,
            CohortBackfillKind.BEHAVIORAL,
            behavioral_cohorts,
            granted_at,
            lambda: create_behavioral_team_run(
                team_id, max_events_per_day=settings.BEHAVIORAL_BACKFILL_MAX_SCAN_EVENTS_PER_DAY
            ),
        ),
        person=_team_run(
            team_id,
            CohortBackfillKind.PERSON_PROPERTY,
            person_cohorts,
            granted_at,
            lambda: create_person_team_backfill_run(
                team_id,
                CohortBackfillTrigger.TEAM_ENABLEMENT,
                settings.BEHAVIORAL_BACKFILL_PERSON_DEFAULT_HORIZON_DAYS,
            ),
        ),
    )
    if enablement.promoted:
        grant_realtime_cohort_access(
            [team_id], level=RealtimeCohortLevel.SERVING, purpose=purpose, save_triggers_backfill=True
        )
    return enablement


def _clear_unmaintained_stamps(team_id: int) -> int:
    # These stamps come from the legacy calculation workflow, or from runs that ran while the env list
    # named the team. Nothing has maintained that membership since, and `serving` routes flags to it.
    # The clear includes deleted cohorts, because an undelete keeps the stamps. It runs before the
    # grant, because from `processing` on the team's own runs stamp its cohorts.
    cleared = Cohort.objects.filter(
        Q(last_backfill_events_at__isnull=False)
        | Q(last_backfill_person_properties_at__isnull=False)
        | Q(last_realtime_cohort_calculation_at__isnull=False),
        team_id=team_id,
    ).update(
        last_backfill_events_at=None,
        last_backfill_person_properties_at=None,
        last_realtime_cohort_calculation_at=None,
    )
    # The update fires no save signal, and the resave rebuilds the flags cache only for the cohorts it
    # changes. Queued even when nothing was cleared, so a rerun after a failed dispatch queues it again.
    transaction.on_commit(lambda: refresh_readiness_caches(team_id))
    return cleared


def _realtime_cohorts(team_id: int) -> list[Cohort]:
    return list(
        Cohort.objects.filter(
            team_id=team_id, cohort_type=CohortType.REALTIME, is_static=False, deleted=False
        ).order_by("id")
    )


def _judge(
    cohorts: list[Cohort], kind: CohortBackfillKind, ineligibility_reason: Callable[[Cohort], str | None]
) -> tuple[list[Cohort], list[CohortRefusal]]:
    eligible: list[Cohort] = []
    refused: list[CohortRefusal] = []
    for cohort in cohorts:
        reason = ineligibility_reason(cohort)
        if reason is None:
            eligible.append(cohort)
        elif reason not in INAPPLICABLE_BACKFILL_REASONS:
            refused.append(CohortRefusal(cohort_id=cohort.id, kind=kind, reason=reason))
    return eligible, refused


def _team_run(
    team_id: int,
    kind: CohortBackfillKind,
    eligible: list[Cohort],
    granted_at: datetime,
    create: Callable[[], CohortBackfillRun],
) -> RunOutcome:
    if not eligible:
        return NothingToBackfill()
    # Runs from before the grant, such as from a time the env list named the team, seeded state the
    # pipeline has since dropped.
    kept = (
        CohortBackfillRun.objects.for_team(team_id)
        .filter(
            scope=CohortBackfillScope.TEAM,
            backfill_kind=kind,
            status__in=_KEPT_RUN_STATUSES,
            created_at__gte=granted_at,
        )
        .order_by("-created_at")
        .first()
    )
    if kept is not None:
        return RunAlreadyCreated(run_id=kept.id)
    # A creator writes its run in one transaction, so a failure of any kind leaves no run behind. The
    # ClickHouse sizing scans fail with errors no narrower type covers.
    try:
        return RunCreated(run_id=create().id)
    except (ValueError, PersonSeedEstimateScanCapExceeded) as error:
        return RunRefused(reason=str(error))
    except Exception as error:
        logger.exception("realtime_enablement_run_failed", team_id=team_id, backfill_kind=kind)
        return RunFailed(reason=str(error))


def create_behavioral_team_run(
    team_id: int,
    *,
    cohort_ids: list[int] | None = None,
    max_events_per_day: int,
    created_by_id: int | None = None,
) -> CohortBackfillRun:
    """A scan limit refusal says how staff accept the volume. A limit of 0 skips the scan estimate."""
    try:
        return create_team_backfill_run(
            team_id,
            CohortBackfillTrigger.TEAM_ENABLEMENT,
            cohort_ids,
            created_by_id,
            max_events_per_day=max_events_per_day,
        )
    except BehavioralScanOverLimit as error:
        raise ValueError(
            f"{error} To accept the volume, start a behavioral backfill that skips the scan limit."
        ) from error


def describe_enablement(team_id: int, enablement: TeamEnablement) -> list[str]:
    level = RealtimeCohortLevel.SERVING if enablement.promoted else RealtimeCohortLevel.PROCESSING
    resave = enablement.resave
    resave_line = (
        f"  Resave: {resave.total} cohorts, {resave.changed} changed, {resave.errors} errors, "
        f"{resave.validation_errors} validation errors"
    )
    if resave.rebuild_dispatch_failed:
        resave_line += ", flags cache rebuild not enqueued"
    return [
        f"Team {team_id}: {level}",
        *(
            [f"  Cleared old readiness stamps: {enablement.cleared_stamps} cohorts"]
            if enablement.cleared_stamps
            else []
        ),
        resave_line,
        *(
            f"  Not backfilled: cohort {refusal.cohort_id}, {refusal.kind}, {refusal.reason}"
            for refusal in enablement.refused_cohorts
        ),
        f"  Behavioral run: {_run_outcome(enablement.behavioral)}",
        f"  Person run: {_run_outcome(enablement.person)}",
    ]


def _run_outcome(outcome: RunOutcome) -> str:
    match outcome:
        case RunCreated(run_id=run_id):
            return f"created {run_id}"
        case RunAlreadyCreated(run_id=run_id):
            return f"already created {run_id}"
        case NothingToBackfill():
            return "nothing to backfill"
        case RunRefused(reason=reason):
            return f"refused, {reason}"
        case RunFailed(reason=reason):
            return f"failed, {reason}"
