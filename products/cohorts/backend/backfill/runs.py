from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Now
from django.utils import timezone as django_timezone

from posthog.models.team.team import Team

from products.cohorts.backend.backfill.pinning import pin_conditions_for_cohorts
from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash
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


def _has_behavioral_filters(cohort: Cohort) -> bool:
    properties = (cohort.filters or {}).get("properties")
    return any(leaf.get("type") == "behavioral" for leaf in walk_filter_leaves(properties))


def _run_status(preconditions_missing: list[str]) -> tuple[str, str]:
    if preconditions_missing:
        reason = f"Missing operator attestations: {', '.join(preconditions_missing)}"
        return CohortBackfillRunStatus.BLOCKED, reason
    return CohortBackfillRunStatus.AWAITING_BOUNDARY, ""


def _pinned_payload(cohorts: Iterable[Cohort]) -> dict[str, Any]:
    pinned, event_names = pin_conditions_for_cohorts(cohorts)
    return {**pinned, "event_names": event_names}


def _active_participation_cohort_ids(team_id: int, cohort_ids: Iterable[int]) -> set[int]:
    return set(
        CohortBackfillRunCohort.objects.for_team(team_id)
        .filter(
            cohort_id__in=cohort_ids,
            superseded_at__isnull=True,
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
        if _active_participation_cohort_ids(team_id, [cohort_id]):
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


def create_team_backfill_run(
    team_id: int,
    trigger_kind: str,
    cohort_ids: Iterable[int] | None = None,
    created_by_id: int | None = None,
    boundary_at: datetime | None = None,
) -> CohortBackfillRun:
    if not is_realtime_cohort_team(team_id):
        raise ValueError(f"Team {team_id} is not in the realtime cohort allowlist")

    if boundary_at is not None:
        if trigger_kind != CohortBackfillTrigger.DISASTER_RECOVERY:
            raise ValueError("boundary_at is only valid for disaster recovery runs")
        if django_timezone.is_naive(boundary_at):
            raise ValueError("boundary_at must include a UTC offset")
        try:
            boundary_at = boundary_at.astimezone(UTC)
        except OverflowError as error:
            raise ValueError("boundary_at falls outside the supported UTC range") from error

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
        conflicting_ids = _active_participation_cohort_ids(team_id, [cohort.id for cohort in cohorts])
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


def supersede_active_runs(team_id: int, cohort_ids: Iterable[int]) -> int:
    cohort_id_set = set(cohort_ids)
    if not cohort_id_set:
        return 0

    with transaction.atomic():
        participations = CohortBackfillRunCohort.objects.for_team(team_id).filter(
            cohort_id__in=cohort_id_set,
            superseded_at__isnull=True,
            run__status__in=ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
        )
        cohort_run_ids = list(
            participations.filter(run__scope=CohortBackfillScope.COHORT).values_list("run_id", flat=True)
        )
        participation_count = participations.update(
            superseded_at=Now(), error="Cohort definition changed during backfill"
        )
        if cohort_run_ids:
            CohortBackfillRun.objects.for_team(team_id).filter(id__in=cohort_run_ids).update(
                status=CohortBackfillRunStatus.SUPERSEDED,
                finished_at=Now(),
                error="Cohort definition changed during backfill",
            )
        return participation_count
