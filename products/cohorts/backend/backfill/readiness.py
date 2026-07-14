from django.db.models.functions import Now

import structlog

from products.cohorts.backend.models.backfill import (
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillScope,
)
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.leaf_shape import extract_leaf_shape_hash

logger = structlog.get_logger(__name__)


def ensure_filters_shape_hash(cohort: Cohort) -> str:
    current_hash = cohort.__dict__.get("filters_shape_hash")
    if current_hash is not None:
        return current_hash

    shape_hash = extract_leaf_shape_hash(cohort.filters)
    updated = Cohort.objects.filter(id=cohort.id, team_id=cohort.team_id, filters_shape_hash__isnull=True).update(
        filters_shape_hash=shape_hash
    )
    if updated:
        cohort.filters_shape_hash = shape_hash
        return shape_hash

    cohort.refresh_from_db(fields=["filters_shape_hash"])
    return cohort.filters_shape_hash or ""


def stamp_events_readiness(run: CohortBackfillRun, cohort_id: int) -> bool:
    """CAS-stamp event readiness for one pinned cohort.

    This update intentionally bypasses signals. B5 must explicitly invalidate feature-flag and
    behavioral-cohort caches after a successful stamp.
    """
    participation = CohortBackfillRunCohort.objects.for_team(run.team_id).get(run_id=run.id, cohort_id=cohort_id)
    updated = Cohort.objects.filter(
        id=cohort_id,
        team_id=run.team_id,
        filters_shape_hash=participation.filters_shape_hash,
        last_backfill_events_at__isnull=True,
    ).update(last_backfill_events_at=Now())
    if updated:
        CohortBackfillRunCohort.objects.for_team(run.team_id).filter(id=participation.id).update(
            stamped_at=Now(), error=""
        )
        return True

    error = "Cohort definition changed or readiness was already stamped"
    CohortBackfillRunCohort.objects.for_team(run.team_id).filter(id=participation.id).update(
        superseded_at=Now(), error=error
    )
    if run.scope == CohortBackfillScope.COHORT:
        CohortBackfillRun.objects.for_team(run.team_id).filter(
            id=run.id,
            status__in=(
                CohortBackfillRunStatus.AWAITING_BOUNDARY,
                CohortBackfillRunStatus.BLOCKED,
                CohortBackfillRunStatus.SEEDING,
                CohortBackfillRunStatus.RECONCILING,
            ),
        ).update(status=CohortBackfillRunStatus.SUPERSEDED, finished_at=Now(), error=error)
    logger.info("cohort_backfill_readiness_stamp_superseded", run_id=str(run.id), cohort_id=cohort_id)
    return False
