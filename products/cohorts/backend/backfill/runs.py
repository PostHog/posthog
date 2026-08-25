from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models.functions import Now
from django.utils import timezone as django_timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.cohorts.backend.backfill.pinning import (
    PersonPinningCapExceeded,
    pin_conditions_for_cohorts,
    pin_person_conditions_for_cohorts,
)
from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash
from products.cohorts.backend.backfill.sizing import (
    PersonSeedEstimate,
    PersonSeedEstimateScanCapExceeded,
    estimate_person_seed_topic_bytes,
)
from products.cohorts.backend.models.backfill import (
    ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillScope,
    CohortBackfillTrigger,
)
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.leaf_shape import walk_filter_leaves
from products.cohorts.backend.realtime_teams import is_realtime_cohort_team

logger = structlog.get_logger(__name__)


def check_run_preconditions() -> tuple[dict[str, Any], list[str]]:
    preconditions = {
        "merge_gate_attested": settings.BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED,
        "durability_attested": settings.BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED,
        "catalog_consume_floor": "not_implemented_b8",
    }
    missing = [
        name
        for name, met in (
            ("merge gate", preconditions["merge_gate_attested"]),
            ("processor durability", preconditions["durability_attested"]),
        )
        if not met
    ]
    return preconditions, missing


def check_person_run_preconditions() -> tuple[dict[str, Any], list[str]]:
    """Person-run gates: the behavioral ones plus person-record TTL and seed sizing.

    Neither is scope-dependent. Every person seed lands in the same ``cf_person_records`` store,
    whose retention Django cannot see (the seeder reads ``COHORT_PERSON_RECORD_TTL_DAYS``), so an
    operator has to attest it for any kind of person run. And both person creators size their seed
    emission against ``BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET``, so sizing is attested for
    any kind of person run too. An unset budget is itself a missing precondition: `over_budget` is a
    strict comparison against it, so with the default of 0 every sized run would refuse anyway,
    after paying for the sizing scan.
    """
    preconditions, missing = check_run_preconditions()
    preconditions["person_ttl_attested"] = settings.BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED
    if not preconditions["person_ttl_attested"]:
        missing.append("person record TTL")
    preconditions["person_sizing_attested"] = settings.BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED
    if not preconditions["person_sizing_attested"]:
        missing.append("person seed sizing")
    preconditions["person_topic_bytes_budget"] = settings.BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET
    if settings.BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET <= 0:
        missing.append("person seed topic-bytes budget")
    return preconditions, missing


def has_behavioral_filters(cohort: Cohort) -> bool:
    properties = (cohort.filters or {}).get("properties")
    return any(leaf.get("type") == "behavioral" for leaf in walk_filter_leaves(properties))


def _has_pinnable_person_filters(cohort: Cohort) -> bool:
    properties = (cohort.filters or {}).get("properties")
    return any(
        leaf.get("type") == "person" and leaf.get("conditionHash") is not None
        for leaf in walk_filter_leaves(properties)
    )


def _contains_person_metadata_leaf(cohort: Cohort) -> bool:
    properties = (cohort.filters or {}).get("properties")
    return any(leaf.get("type") == "person_metadata" for leaf in walk_filter_leaves(properties))


def person_backfill_ineligibility_reason(cohort: Cohort) -> str | None:
    """The single person-run eligibility predicate, shared by the creators, the management command,
    and the dispatch receiver so none of them can judge a cohort backfillable that another refuses."""
    if cohort.cohort_type != CohortType.REALTIME:
        return "not realtime"
    if cohort.is_static:
        return "static"
    if cohort.deleted:
        return "deleted"
    if _contains_person_metadata_leaf(cohort):
        return "contains person_metadata filters"
    if not _has_pinnable_person_filters(cohort):
        return "has no person filter with a condition hash"
    return None


def _run_status(preconditions_missing: list[str]) -> tuple[str, str]:
    if preconditions_missing:
        reason = f"Missing operator attestations: {', '.join(preconditions_missing)}"
        return CohortBackfillRunStatus.BLOCKED, reason
    return CohortBackfillRunStatus.AWAITING_BOUNDARY, ""


def _pinned_payload(cohorts: Iterable[Cohort]) -> dict[str, Any]:
    pinned, event_names = pin_conditions_for_cohorts(cohorts)
    return {**pinned, "event_names": event_names}


def _active_participation_cohort_ids(team_id: int, cohort_ids: Iterable[int], *, kind: CohortBackfillKind) -> set[int]:
    return set(
        CohortBackfillRunCohort.objects.for_team(team_id)
        .filter(
            cohort_id__in=cohort_ids,
            superseded_at__isnull=True,
            run__backfill_kind=kind,
            run__status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
        )
        .values_list("cohort_id", flat=True)
    )


def _has_active_cohort_run(team_id: int, cohort_id: int, *, kind: CohortBackfillKind) -> bool:
    """Mirror of the ``cohort_bfr_active_cohort_kind_uq`` predicate. The participation check above
    misses a run whose participation the seeder already superseded (``record_participation_partial``)
    while the run itself stays active and so still holds the per-cohort uniqueness slot."""
    return (
        CohortBackfillRun.objects.for_team(team_id)
        .filter(cohort_id=cohort_id, backfill_kind=kind, status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES)
        .exists()
    )


def _has_active_team_run(team_id: int, *, kind: CohortBackfillKind) -> bool:
    """Mirror of the ``cohort_bfr_active_team_kind_uq`` predicate, for the same divergent state as
    ``_has_active_cohort_run``: a team run whose participations are all superseded is invisible to
    the participation check but still violates the constraint."""
    return (
        CohortBackfillRun.objects.for_team(team_id)
        .filter(scope=CohortBackfillScope.TEAM, backfill_kind=kind, status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES)
        .exists()
    )


def _active_person_seed_topic_bytes(team_id: int) -> int:
    """Sum of the sizing estimates recorded on the team's active person runs.

    The budget has to bound the team's in-flight person seed bytes as a whole, not each run alone:
    the seeder's person scan is team-wide per run, and the per-cohort uniqueness constraint lets one
    run per cohort stack, so runs that each fit the budget can still add up to many multiples of it.
    """
    return sum(
        preconditions.get("person_seed_estimated_topic_bytes", 0)
        for preconditions in CohortBackfillRun.objects.for_team(team_id)
        .filter(
            backfill_kind=CohortBackfillKind.PERSON_PROPERTY,
            status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
        )
        .values_list("preconditions", flat=True)
    )


class BackfillRefusalReason(StrEnum):
    """Why a creator declined to make a run.

    The creators have always refused by returning ``None``, which collapsed a budget refusal and an
    occupied run slot into the same signal — the two need entirely different operator responses
    (raise the budget vs. go unwedge a stuck run), so the metric has to tell them apart.
    """

    TEAM_NOT_REALTIME = "team_not_realtime"
    COHORT_MISSING = "cohort_missing"
    COHORT_INELIGIBLE = "cohort_ineligible"
    PARTICIPATION_ACTIVE = "participation_active"
    RUN_SLOT_OCCUPIED = "run_slot_occupied"
    SLOT_RACE = "slot_race"
    INVALID_HORIZON = "invalid_horizon"
    PINNING_CAP_EXCEEDED = "pinning_cap_exceeded"
    OVER_BUDGET = "over_budget"
    SIZING_SCAN_CAP_EXCEEDED = "sizing_scan_cap_exceeded"
    DEFINITION_CHANGED = "definition_changed"


@frozen
class BackfillRunAttempt:
    """A creator's outcome: the run, or the reason there isn't one. Exactly one is set."""

    run: CohortBackfillRun | None
    reason: BackfillRefusalReason | None

    @classmethod
    def created(cls, run: CohortBackfillRun) -> "BackfillRunAttempt":
        return cls(run=run, reason=None)

    @classmethod
    def refused(cls, reason: BackfillRefusalReason) -> "BackfillRunAttempt":
        return cls(run=None, reason=reason)


def create_backfill_run_for_cohort(team_id: int, cohort_id: int, trigger_kind: str) -> CohortBackfillRun | None:
    """The run, or ``None``, for callers that assert on the run and never on why one was refused."""
    return attempt_backfill_run_for_cohort(team_id, cohort_id, trigger_kind).run


def attempt_backfill_run_for_cohort(team_id: int, cohort_id: int, trigger_kind: str) -> BackfillRunAttempt:
    """Create one cohort's behavioral run, reporting the refusal reason rather than raising.

    Every conflict check is re-run under a row lock, so a cohort edited again, deleted, or made
    static in the meantime refuses instead of creating a second run for the same slot. The reason
    comes back on the attempt so the signal path can label its metric with it.
    """
    if not is_realtime_cohort_team(team_id):
        return BackfillRunAttempt.refused(BackfillRefusalReason.TEAM_NOT_REALTIME)

    try:
        with transaction.atomic():
            cohort = (
                Cohort.objects.select_for_update(of=("self",))
                .select_related("team")
                .filter(id=cohort_id, team_id=team_id)
                .first()
            )
            if cohort is None:
                return BackfillRunAttempt.refused(BackfillRefusalReason.COHORT_MISSING)
            if (
                cohort.cohort_type != CohortType.REALTIME
                or cohort.is_static
                or cohort.deleted
                or not has_behavioral_filters(cohort)
            ):
                return BackfillRunAttempt.refused(BackfillRefusalReason.COHORT_INELIGIBLE)
            if _active_participation_cohort_ids(team_id, [cohort_id], kind=CohortBackfillKind.BEHAVIORAL):
                return BackfillRunAttempt.refused(BackfillRefusalReason.PARTICIPATION_ACTIVE)
            if _has_active_cohort_run(team_id, cohort_id, kind=CohortBackfillKind.BEHAVIORAL):
                return BackfillRunAttempt.refused(BackfillRefusalReason.RUN_SLOT_OCCUPIED)

            filters_shape_hash = ensure_filters_shape_hash(cohort)
            behavioral_filters_shape_hash = cohort.behavioral_filters_shape_hash or ""
            preconditions, missing = check_run_preconditions()
            status, blocked_reason = _run_status(missing)
            run = CohortBackfillRun.objects.for_team(team_id).create(
                team_id=team_id,
                cohort=cohort,
                backfill_kind=CohortBackfillKind.BEHAVIORAL,
                trigger_kind=trigger_kind,
                scope=CohortBackfillScope.COHORT,
                status=status,
                timezone=cohort.team.timezone,
                pinned=_pinned_payload([cohort]),
                preconditions=preconditions,
                blocked_reason=blocked_reason,
            )
            CohortBackfillRunCohort.objects.for_team(team_id).create(
                run=run,
                team_id=team_id,
                cohort=cohort,
                filters_shape_hash=filters_shape_hash,
                behavioral_filters_shape_hash=behavioral_filters_shape_hash,
                pinned_filters=cohort.filters,
            )
            return BackfillRunAttempt.created(run)
    except IntegrityError:
        # A writer this transaction could not see won the unique-constraint race after the conflict
        # checks passed. Refusing is this creator's contract, so report the race rather than raise.
        logger.warning(
            "cohort_backfill_run_conflict_race",
            team_id=team_id,
            cohort_id=cohort_id,
            backfill_kind=CohortBackfillKind.BEHAVIORAL,
        )
        return BackfillRunAttempt.refused(BackfillRefusalReason.SLOT_RACE)


def _validate_boundary_at(trigger_kind: str, boundary_at: datetime | None) -> datetime | None:
    if boundary_at is None:
        return None
    if trigger_kind != CohortBackfillTrigger.DISASTER_RECOVERY:
        raise ValueError("boundary_at is only valid for disaster recovery runs")
    if django_timezone.is_naive(boundary_at):
        raise ValueError("boundary_at must include a UTC offset")
    try:
        return boundary_at.astimezone(UTC)
    except OverflowError as error:
        raise ValueError("boundary_at falls outside the supported UTC range") from error


def create_team_backfill_run(
    team_id: int,
    trigger_kind: str,
    cohort_ids: Iterable[int] | None = None,
    created_by_id: int | None = None,
    boundary_at: datetime | None = None,
) -> CohortBackfillRun:
    if not is_realtime_cohort_team(team_id):
        raise ValueError(f"Team {team_id} is not in the realtime cohort allowlist")

    boundary_at = _validate_boundary_at(trigger_kind, boundary_at)

    requested_ids = set(cohort_ids) if cohort_ids is not None else None
    with transaction.atomic():
        team = Team.objects.get(id=team_id)
        queryset = Cohort.objects.select_for_update(of=("self",)).filter(
            team_id=team_id,
            cohort_type=CohortType.REALTIME,
            is_static=False,
            deleted=False,
        )
        if requested_ids is not None:
            queryset = queryset.filter(id__in=requested_ids)
        cohorts = [cohort for cohort in queryset.order_by("id") if has_behavioral_filters(cohort)]
        if requested_ids is not None and {cohort.id for cohort in cohorts} != requested_ids:
            invalid_ids = sorted(requested_ids - {cohort.id for cohort in cohorts})
            raise ValueError(f"Cohorts are not eligible realtime behavioral cohorts: {invalid_ids}")
        if not cohorts:
            raise ValueError(f"Team {team_id} has no eligible realtime behavioral cohorts")
        conflicting_ids = _active_participation_cohort_ids(
            team_id, [cohort.id for cohort in cohorts], kind=CohortBackfillKind.BEHAVIORAL
        )
        if conflicting_ids:
            raise ValueError(f"Cohorts already have active backfill runs: {sorted(conflicting_ids)}")
        if _has_active_team_run(team_id, kind=CohortBackfillKind.BEHAVIORAL):
            raise ValueError(f"Team {team_id} already has an active team backfill run (behavioral)")

        hashes: dict[int, str] = {}
        behavioral_hashes: dict[int, str] = {}
        for cohort in cohorts:
            hashes[cohort.id] = ensure_filters_shape_hash(cohort)
            behavioral_hashes[cohort.id] = cohort.behavioral_filters_shape_hash or ""
        preconditions, missing = check_run_preconditions()
        status, blocked_reason = _run_status(missing)
        run = CohortBackfillRun.objects.for_team(team_id).create(
            team_id=team_id,
            created_by_id=created_by_id,
            backfill_kind=CohortBackfillKind.BEHAVIORAL,
            trigger_kind=trigger_kind,
            scope=CohortBackfillScope.TEAM,
            status=status,
            boundary_at=boundary_at,
            timezone=team.timezone,
            pinned=_pinned_payload(cohorts),
            preconditions=preconditions,
            blocked_reason=blocked_reason,
        )
        CohortBackfillRunCohort.objects.for_team(team_id).bulk_create(
            [
                CohortBackfillRunCohort(
                    run=run,
                    team_id=team_id,
                    cohort=cohort,
                    filters_shape_hash=hashes[cohort.id],
                    behavioral_filters_shape_hash=behavioral_hashes[cohort.id],
                    pinned_filters=cohort.filters,
                )
                for cohort in cohorts
            ]
        )
        return run


def create_person_backfill_run_for_cohort(
    team_id: int,
    cohort_id: int,
    trigger_kind: str,
    *,
    person_horizon_days: int | None = None,
) -> CohortBackfillRun | None:
    """The run, or ``None``, for callers that assert on the run and never on why one was refused."""
    return attempt_person_backfill_run_for_cohort(
        team_id, cohort_id, trigger_kind, person_horizon_days=person_horizon_days
    ).run


def attempt_person_backfill_run_for_cohort(
    team_id: int,
    cohort_id: int,
    trigger_kind: str,
    *,
    person_horizon_days: int | None = None,
) -> BackfillRunAttempt:
    """Create one cohort's person-property run, on the signal path's contract.

    Unlike ``create_person_team_backfill_run`` this refuses quietly where the team creator raises:
    it is the target of ``cohort_person_shape_changed_backfill``, where a refusal must warn and
    return rather than fail the Celery task. That is also why the horizon defaults from settings
    here but is required on the operator-driven team creator. The one exception is a transient
    sizing failure (a ClickHouse timeout or transport error), which propagates so the task's retry
    machinery re-runs it; the scan's own deterministic read cap still refuses quietly, since
    retrying it would only repeat the capped scan.

    The reason for a refusal comes back on the attempt, so the signal path can label its metric
    with it.
    """
    if not is_realtime_cohort_team(team_id):
        return BackfillRunAttempt.refused(BackfillRefusalReason.TEAM_NOT_REALTIME)

    horizon_days = (
        person_horizon_days
        if person_horizon_days is not None
        else settings.BEHAVIORAL_BACKFILL_PERSON_DEFAULT_HORIZON_DAYS
    )
    if horizon_days < 1:
        logger.warning(
            "cohort_person_backfill_invalid_horizon",
            team_id=team_id,
            cohort_id=cohort_id,
            person_horizon_days=horizon_days,
        )
        return BackfillRunAttempt.refused(BackfillRefusalReason.INVALID_HORIZON)

    # Unlocked pre-pass for the sizing gate: the estimate is a ClickHouse round trip, so it must not
    # run while the create path below holds the cohort row FOR UPDATE. The locked pass re-derives
    # eligibility and the pin, and refuses if the definition moved in between.
    cohort = Cohort.objects.filter(id=cohort_id, team_id=team_id).first()
    if cohort is None:
        return BackfillRunAttempt.refused(BackfillRefusalReason.COHORT_MISSING)
    if person_backfill_ineligibility_reason(cohort) is not None:
        return BackfillRunAttempt.refused(BackfillRefusalReason.COHORT_INELIGIBLE)
    if _active_participation_cohort_ids(team_id, [cohort_id], kind=CohortBackfillKind.PERSON_PROPERTY):
        return BackfillRunAttempt.refused(BackfillRefusalReason.PARTICIPATION_ACTIVE)
    if _has_active_cohort_run(team_id, cohort_id, kind=CohortBackfillKind.PERSON_PROPERTY):
        return BackfillRunAttempt.refused(BackfillRefusalReason.RUN_SLOT_OCCUPIED)
    try:
        pinned = pin_person_conditions_for_cohorts(
            [cohort],
            max_conditions=settings.BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS,
        )
    except PersonPinningCapExceeded:
        logger.warning(
            "cohort_person_backfill_pinning_cap_exceeded",
            team_id=team_id,
            cohort_id=cohort_id,
            max_conditions=settings.BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS,
        )
        return BackfillRunAttempt.refused(BackfillRefusalReason.PINNING_CAP_EXCEEDED)

    person_scan_since = django_timezone.now() - timedelta(days=horizon_days)
    # With a precondition missing the run below records as `blocked`, which the seeder never claims,
    # so paying for the sizing scan would buy nothing.
    preconditions, missing = check_person_run_preconditions()
    estimate: PersonSeedEstimate | None = None
    if not missing:
        # A budget already consumed by in-flight runs refuses before the estimate on purpose: the
        # estimate is the team-wide sizing scan, and dispatch is debounced per cohort, so N edited
        # cohorts would otherwise each pay a scan only to be refused here one by one. Expensive
        # scans record large estimates, so the teams whose scans cost the most stop scanning first.
        active_topic_bytes = _active_person_seed_topic_bytes(team_id)
        if active_topic_bytes >= settings.BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET:
            logger.warning(
                "cohort_person_backfill_over_budget",
                team_id=team_id,
                cohort_id=cohort_id,
                active_topic_bytes=active_topic_bytes,
                budget_bytes=settings.BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET,
            )
            return BackfillRunAttempt.refused(BackfillRefusalReason.OVER_BUDGET)
        try:
            estimate = estimate_person_seed_topic_bytes(team_id, person_scan_since, len(pinned["conditions"]))
        except PersonSeedEstimateScanCapExceeded as error:
            logger.warning(
                "cohort_person_backfill_sizing_failed",
                team_id=team_id,
                cohort_id=cohort_id,
                error=str(error),
            )
            return BackfillRunAttempt.refused(BackfillRefusalReason.SIZING_SCAN_CAP_EXCEEDED)
        if estimate.estimated_topic_bytes + active_topic_bytes > estimate.budget_bytes:
            logger.warning(
                "cohort_person_backfill_over_budget",
                team_id=team_id,
                cohort_id=cohort_id,
                estimated_topic_bytes=estimate.estimated_topic_bytes,
                active_topic_bytes=active_topic_bytes,
                budget_bytes=estimate.budget_bytes,
            )
            return BackfillRunAttempt.refused(BackfillRefusalReason.OVER_BUDGET)

    try:
        with transaction.atomic():
            # The locked re-checks reuse the unlocked reasons on purpose: which pass caught the
            # refusal is a debugging detail for the log line, not a dimension worth doubling the
            # metric's cardinality for.
            cohort = (
                Cohort.objects.select_for_update(of=("self",))
                .select_related("team")
                .filter(id=cohort_id, team_id=team_id)
                .first()
            )
            if cohort is None:
                return BackfillRunAttempt.refused(BackfillRefusalReason.COHORT_MISSING)
            if person_backfill_ineligibility_reason(cohort) is not None:
                return BackfillRunAttempt.refused(BackfillRefusalReason.COHORT_INELIGIBLE)
            if _active_participation_cohort_ids(team_id, [cohort_id], kind=CohortBackfillKind.PERSON_PROPERTY):
                return BackfillRunAttempt.refused(BackfillRefusalReason.PARTICIPATION_ACTIVE)
            if _has_active_cohort_run(team_id, cohort_id, kind=CohortBackfillKind.PERSON_PROPERTY):
                return BackfillRunAttempt.refused(BackfillRefusalReason.RUN_SLOT_OCCUPIED)

            try:
                locked_pinned = pin_person_conditions_for_cohorts(
                    [cohort],
                    max_conditions=settings.BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS,
                )
            except PersonPinningCapExceeded:
                logger.warning(
                    "cohort_person_backfill_pinning_cap_exceeded",
                    team_id=team_id,
                    cohort_id=cohort_id,
                    max_conditions=settings.BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS,
                )
                return BackfillRunAttempt.refused(BackfillRefusalReason.PINNING_CAP_EXCEEDED)
            if locked_pinned != pinned:
                # A racing edit changed the definition after sizing; its own save dispatched a fresh
                # debounced task, so that task owns the re-sized run.
                logger.warning(
                    "cohort_person_backfill_definition_changed_during_sizing",
                    team_id=team_id,
                    cohort_id=cohort_id,
                )
                return BackfillRunAttempt.refused(BackfillRefusalReason.DEFINITION_CHANGED)

            filters_shape_hash = ensure_filters_shape_hash(cohort)
            person_filters_shape_hash = cohort.person_filters_shape_hash or ""
            status, blocked_reason = _run_status(missing)
            run = CohortBackfillRun.objects.for_team(team_id).create(
                team_id=team_id,
                cohort=cohort,
                backfill_kind=CohortBackfillKind.PERSON_PROPERTY,
                trigger_kind=trigger_kind,
                scope=CohortBackfillScope.COHORT,
                status=status,
                timezone=cohort.team.timezone,
                person_scan_since=person_scan_since,
                pinned={**pinned, "person_horizon_days": horizon_days},
                preconditions={**preconditions, **(estimate.as_preconditions() if estimate else {})},
                blocked_reason=blocked_reason,
            )
            CohortBackfillRunCohort.objects.for_team(team_id).create(
                run=run,
                team_id=team_id,
                cohort=cohort,
                filters_shape_hash=filters_shape_hash,
                person_filters_shape_hash=person_filters_shape_hash,
                pinned_filters=cohort.filters,
            )
            return BackfillRunAttempt.created(run)
    except IntegrityError:
        # A writer this transaction could not see won the unique-constraint race after the conflict
        # checks passed. Refusing is this creator's contract, so report the race rather than raise.
        logger.warning(
            "cohort_backfill_run_conflict_race",
            team_id=team_id,
            cohort_id=cohort_id,
            backfill_kind=CohortBackfillKind.PERSON_PROPERTY,
        )
        return BackfillRunAttempt.refused(BackfillRefusalReason.SLOT_RACE)


def _person_cohorts_for_team(team_id: int, requested_ids: set[int] | None, *, lock: bool) -> list[Cohort]:
    # Narrow on the SQL-expressible half of eligibility before locking: `select_for_update` locks
    # every row the query returns, so an unnarrowed team scan would hold `FOR UPDATE` on static,
    # deleted, and non-realtime cohorts that were never candidates, blocking edits to them.
    queryset = Cohort.objects.filter(
        team_id=team_id,
        cohort_type=CohortType.REALTIME,
        is_static=False,
        deleted=False,
    )
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    if requested_ids is not None:
        queryset = queryset.filter(id__in=requested_ids)
    candidates = list(queryset.order_by("id"))
    cohorts = [cohort for cohort in candidates if person_backfill_ineligibility_reason(cohort) is None]

    if requested_ids is not None and {cohort.id for cohort in cohorts} != requested_ids:
        invalid_ids = sorted(requested_ids - {cohort.id for cohort in cohorts})
        raise ValueError(f"Cohorts are not eligible realtime person-property cohorts: {invalid_ids}")
    if not cohorts:
        raise ValueError(f"Team {team_id} has no eligible realtime person-property cohorts")
    return cohorts


def create_person_team_backfill_run(
    team_id: int,
    trigger_kind: str,
    person_horizon_days: int,
    cohort_ids: Iterable[int] | None = None,
    created_by_id: int | None = None,
    boundary_at: datetime | None = None,
) -> CohortBackfillRun:
    if not is_realtime_cohort_team(team_id):
        raise ValueError(f"Team {team_id} is not in the realtime cohort allowlist")
    if person_horizon_days < 1:
        raise ValueError("person_horizon_days must be at least 1")

    boundary_at = _validate_boundary_at(trigger_kind, boundary_at)
    preconditions, missing = check_person_run_preconditions()
    if missing:
        raise ValueError(f"Missing operator attestations: {', '.join(missing)}")

    requested_ids = set(cohort_ids) if cohort_ids is not None else None
    cohorts = _person_cohorts_for_team(team_id, requested_ids, lock=False)
    pinned = pin_person_conditions_for_cohorts(
        cohorts,
        max_conditions=settings.BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS,
    )
    person_scan_since = (boundary_at or django_timezone.now()) - timedelta(days=person_horizon_days)
    estimate = estimate_person_seed_topic_bytes(
        team_id,
        person_scan_since,
        len(pinned["conditions"]),
    )
    if estimate.over_budget:
        raise ValueError(
            f"Estimated person seed topic bytes {estimate.estimated_topic_bytes} exceed budget {estimate.budget_bytes}"
        )

    with transaction.atomic():
        team = Team.objects.get(id=team_id)
        cohorts = _person_cohorts_for_team(team_id, requested_ids, lock=True)
        locked_pinned = pin_person_conditions_for_cohorts(
            cohorts,
            max_conditions=settings.BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS,
        )
        if locked_pinned != pinned:
            raise ValueError("Cohort person-property definitions changed during sizing; retry the run")

        conflicting_ids = _active_participation_cohort_ids(
            team_id,
            [cohort.id for cohort in cohorts],
            kind=CohortBackfillKind.PERSON_PROPERTY,
        )
        if conflicting_ids:
            raise ValueError(f"Cohorts already have active person-property backfill runs: {sorted(conflicting_ids)}")
        if _has_active_team_run(team_id, kind=CohortBackfillKind.PERSON_PROPERTY):
            raise ValueError(f"Team {team_id} already has an active team backfill run (person_property)")

        hashes: dict[int, str] = {}
        person_hashes: dict[int, str] = {}
        for cohort in cohorts:
            hashes[cohort.id] = ensure_filters_shape_hash(cohort)
            person_hashes[cohort.id] = cohort.person_filters_shape_hash or ""

        run = CohortBackfillRun.objects.for_team(team_id).create(
            team_id=team_id,
            created_by_id=created_by_id,
            backfill_kind=CohortBackfillKind.PERSON_PROPERTY,
            trigger_kind=trigger_kind,
            scope=CohortBackfillScope.TEAM,
            status=CohortBackfillRunStatus.AWAITING_BOUNDARY,
            boundary_at=boundary_at,
            person_scan_since=person_scan_since,
            timezone=team.timezone,
            pinned={**pinned, "person_horizon_days": person_horizon_days},
            preconditions={**preconditions, **estimate.as_preconditions()},
        )
        CohortBackfillRunCohort.objects.for_team(team_id).bulk_create(
            [
                CohortBackfillRunCohort(
                    run=run,
                    team_id=team_id,
                    cohort=cohort,
                    filters_shape_hash=hashes[cohort.id],
                    person_filters_shape_hash=person_hashes[cohort.id],
                    pinned_filters=cohort.filters,
                )
                for cohort in cohorts
            ]
        )
        return run


def supersede_active_runs(team_id: int, cohort_ids: Iterable[int], *, kind: CohortBackfillKind) -> int:
    """Returns the number of participations newly superseded, not everything written: superseding a
    run whose participation the seeder already terminalized returns 0."""
    cohort_id_set = set(cohort_ids)
    if not cohort_id_set:
        return 0

    error = "Cohort definition changed during backfill"
    with transaction.atomic():
        # Resolve the targets first, then write run rows before participation rows. The finalizer
        # locks in that order (run FOR UPDATE, then participations via the readiness stamp), so
        # the opposite order here would deadlock the two on a cohort-scoped run.
        targets = list(
            CohortBackfillRunCohort.objects.for_team(team_id)
            .filter(
                cohort_id__in=cohort_id_set,
                superseded_at__isnull=True,
                run__backfill_kind=kind,
                run__status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
            )
            .values_list("id", "run_id", "run__scope")
        )
        # Cohort-scoped runs are also targeted through the run's own cohort column: a seeder partial
        # outcome (`record_participation_partial`) supersedes the participation while the run stays
        # active, and an active run holds the per-cohort uniqueness slot whether or not its
        # participation is already terminal.
        cohort_run_ids = set(
            CohortBackfillRun.objects.for_team(team_id)
            .filter(
                cohort_id__in=cohort_id_set,
                backfill_kind=kind,
                status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
            )
            .values_list("id", flat=True)
        )
        cohort_run_ids.update(run_id for _, run_id, scope in targets if scope == CohortBackfillScope.COHORT)
        if not targets and not cohort_run_ids:
            return 0

        if cohort_run_ids:
            CohortBackfillRun.objects.for_team(team_id).filter(id__in=cohort_run_ids).update(
                status=CohortBackfillRunStatus.SUPERSEDED,
                finished_at=Now(),
                error=error,
            )
        return (
            CohortBackfillRunCohort.objects.for_team(team_id)
            .filter(id__in=[participation_id for participation_id, _, _ in targets], superseded_at__isnull=True)
            .update(superseded_at=Now(), error=error)
        )
