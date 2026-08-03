from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Now
from django.utils import timezone as django_timezone

import structlog

from posthog.models.team.team import Team

from products.cohorts.backend.backfill.pinning import (
    PersonPinningCapExceeded,
    pin_conditions_for_cohorts,
    pin_person_conditions_for_cohorts,
)
from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash
from products.cohorts.backend.backfill.sizing import estimate_person_seed_topic_bytes
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


def check_person_run_preconditions(*, requires_sizing_attestation: bool) -> tuple[dict[str, Any], list[str]]:
    """Person-run gates: the behavioral ones plus person-record TTL, and sizing for team runs.

    TTL is not scope-dependent — every person seed lands in the same ``cf_person_records`` store,
    whose retention Django cannot see (the seeder reads ``COHORT_PERSON_RECORD_TTL_DAYS``), so an
    operator has to attest it for any kind of person run. Only the team creator estimates topic
    bytes, so only it requires the sizing attestation.
    """
    preconditions, missing = check_run_preconditions()
    preconditions["person_ttl_attested"] = settings.BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED
    if not preconditions["person_ttl_attested"]:
        missing.append("person record TTL")
    if requires_sizing_attestation:
        preconditions["person_sizing_attested"] = settings.BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED
        if not preconditions["person_sizing_attested"]:
            missing.append("person seed sizing")
    return preconditions, missing


def _has_behavioral_filters(cohort: Cohort) -> bool:
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


def _person_backfill_ineligibility_reason(cohort: Cohort) -> str | None:
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


def create_backfill_run_for_cohort(team_id: int, cohort_id: int, trigger_kind: str) -> CohortBackfillRun | None:
    if not is_realtime_cohort_team(team_id):
        return None

    with transaction.atomic():
        cohort = (
            Cohort.objects.select_for_update(of=("self",))
            .select_related("team")
            .filter(id=cohort_id, team_id=team_id)
            .first()
        )
        if (
            cohort is None
            or cohort.cohort_type != CohortType.REALTIME
            or cohort.is_static
            or cohort.deleted
            or not _has_behavioral_filters(cohort)
        ):
            return None
        if _active_participation_cohort_ids(team_id, [cohort_id], kind=CohortBackfillKind.BEHAVIORAL):
            return None

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
        return run


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
        cohorts = [cohort for cohort in queryset.order_by("id") if _has_behavioral_filters(cohort)]
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
    """Create one cohort's person-property run, on the signal path's contract.

    Unlike ``create_person_team_backfill_run`` this never raises and never touches ClickHouse: it
    becomes the target of the person counterpart to the behavioral shape-changed receiver (B7.3b),
    where a refusal has to warn and return rather than fail the Celery task. That is also why the
    horizon defaults from settings here but is required on the operator-driven team creator.
    """
    if not is_realtime_cohort_team(team_id):
        return None

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
        return None

    with transaction.atomic():
        cohort = (
            Cohort.objects.select_for_update(of=("self",))
            .select_related("team")
            .filter(id=cohort_id, team_id=team_id)
            .first()
        )
        if cohort is None or _person_backfill_ineligibility_reason(cohort) is not None:
            return None
        if _active_participation_cohort_ids(team_id, [cohort_id], kind=CohortBackfillKind.PERSON_PROPERTY):
            return None

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
            return None

        filters_shape_hash = ensure_filters_shape_hash(cohort)
        person_filters_shape_hash = cohort.person_filters_shape_hash or ""
        preconditions, missing = check_person_run_preconditions(requires_sizing_attestation=False)
        status, blocked_reason = _run_status(missing)
        person_scan_since = django_timezone.now() - timedelta(days=horizon_days)
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
            preconditions=preconditions,
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
        return run


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
    cohorts = [cohort for cohort in candidates if _person_backfill_ineligibility_reason(cohort) is None]

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
    preconditions, missing = check_person_run_preconditions(requires_sizing_attestation=True)
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
    cohort_id_set = set(cohort_ids)
    if not cohort_id_set:
        return 0

    error = "Cohort definition changed during backfill"
    with transaction.atomic():
        # Resolve the targets first, then write run rows before participation rows. The finalizer
        # locks in that order (run FOR UPDATE, then participations via stamp_events_readiness), so
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
        if not targets:
            return 0

        cohort_run_ids = [run_id for _, run_id, scope in targets if scope == CohortBackfillScope.COHORT]
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
