from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from django.conf import settings

import structlog

from posthog.cohort_resave import CohortResaveStats, resave_team_cohorts, termination_unwinds, unclassified_cohort_ids
from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.cohorts.backend.backfill.pinning import pin_behavioral_run
from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash
from products.cohorts.backend.backfill.runs import (
    INAPPLICABLE_BACKFILL_REASONS,
    behavioral_backfill_ineligibility_reason,
    check_person_run_preconditions,
    create_person_team_backfill_run,
    create_team_backfill_run,
    person_backfill_ineligibility_reason,
)
from products.cohorts.backend.backfill.sizing import estimate_behavioral_scan_events
from products.cohorts.backend.models.backfill import (
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


type RunOutcome = RunCreated | RunAlreadyCreated | NothingToBackfill | RunRefused


@frozen
class CohortRefusal:
    cohort_id: int
    kind: CohortBackfillKind
    reason: str


@frozen
class TeamEnablement:
    resave: CohortResaveStats
    unclassified_cohort_ids: tuple[int, ...]
    refused_cohorts: tuple[CohortRefusal, ...]
    behavioral: RunOutcome
    person: RunOutcome

    @property
    def promoted(self) -> bool:
        return not isinstance(self.behavioral, RunRefused) and not isinstance(self.person, RunRefused)


@frozen
class AlreadyServing:
    pass


def enable_realtime_cohorts(team_id: int, *, purpose: RealtimeCohortAccessPurpose) -> TeamEnablement | AlreadyServing:
    """Put the team at `processing` with its cohorts ready for the pipeline, create its two team
    backfill runs, and promote it to `serving` only when neither run was refused.

    Raises ``ValueError`` before it writes anything for a team the grant refuses, or when an operator
    attestation is missing. A call after a refusal keeps the runs earlier calls created.
    """
    row = grantable_access_rows([team_id], purpose, RealtimeCohortTeamAccess.objects.all()).get(team_id)
    # The steps below go through `processing`, which would hide a serving team's realtime state.
    if row is not None and row.level == RealtimeCohortLevel.SERVING:
        return AlreadyServing()
    # Without them neither team run can be created, so the team would only sit at `processing`.
    _, missing = check_person_run_preconditions()
    if missing:
        raise ValueError(f"Missing operator attestations: {', '.join(missing)}")

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
        resave=resave,
        unclassified_cohort_ids=tuple(unclassified_cohort_ids([team_id])),
        refused_cohorts=(*behavioral_refusals, *person_refusals),
        behavioral=_team_run(
            team_id,
            CohortBackfillKind.BEHAVIORAL,
            behavioral_cohorts,
            granted_at,
            lambda: _create_behavioral_team_run(team, behavioral_cohorts),
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
    except ValueError as error:
        return RunRefused(reason=str(error))
    except Exception as error:
        logger.exception("realtime_enablement_run_failed", team_id=team_id, backfill_kind=kind)
        return RunRefused(reason=str(error))


def _create_behavioral_team_run(team: Team, eligible: list[Cohort]) -> CohortBackfillRun:
    """`create_team_backfill_run` behind the scan limit of `create_cohort_backfill_run`, refusing with
    ``ValueError`` like the person creator."""
    max_events_per_day = settings.BEHAVIORAL_BACKFILL_MAX_SCAN_EVENTS_PER_DAY
    if not max_events_per_day:
        return create_team_backfill_run(team.id, CohortBackfillTrigger.TEAM_ENABLEMENT)
    pinned = pin_behavioral_run(eligible, team)
    estimate = estimate_behavioral_scan_events(
        team.id,
        pinned["event_names"],
        flag_calls_table=pinned["flag_calls_table"],
        max_events_per_day=max_events_per_day,
    )
    if estimate.over_limit:
        raise ValueError(
            f"The run would scan {estimate.peak_day_events} events on its busiest day ({estimate.peak_day}), "
            f"above the limit of {estimate.max_events_per_day}. Narrow it with create_cohort_backfill_run "
            "--cohort-ids, or accept the volume with its --max-scan-events-per-day, then run enable again."
        )
    return create_team_backfill_run(team.id, CohortBackfillTrigger.TEAM_ENABLEMENT, scan_estimate=estimate)
