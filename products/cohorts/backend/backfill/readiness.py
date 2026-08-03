from django.db.models.functions import Now

import structlog

from products.cohorts.backend.models.backfill import (
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillScope,
)
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.leaf_shape import (
    extract_behavioral_leaf_shape_hash,
    extract_leaf_shape_hash,
    extract_person_leaf_shape_hash,
)

logger = structlog.get_logger(__name__)


def ensure_filters_shape_hash(cohort: Cohort) -> str:
    current_hash = cohort.__dict__.get("filters_shape_hash")
    if current_hash is None:
        shape_hash = extract_leaf_shape_hash(cohort.filters)
        updated = Cohort.objects.filter(id=cohort.id, team_id=cohort.team_id, filters_shape_hash__isnull=True).update(
            filters_shape_hash=shape_hash
        )
        if updated:
            cohort.filters_shape_hash = shape_hash
        else:
            cohort.refresh_from_db(fields=["filters_shape_hash"])

    if cohort.__dict__.get("behavioral_filters_shape_hash") is None:
        behavioral_shape_hash = extract_behavioral_leaf_shape_hash(cohort.filters)
        updated = Cohort.objects.filter(
            id=cohort.id,
            team_id=cohort.team_id,
            behavioral_filters_shape_hash__isnull=True,
        ).update(behavioral_filters_shape_hash=behavioral_shape_hash)
        if updated:
            cohort.behavioral_filters_shape_hash = behavioral_shape_hash
        else:
            cohort.refresh_from_db(fields=["behavioral_filters_shape_hash"])

    if cohort.__dict__.get("person_filters_shape_hash") is None:
        person_shape_hash = extract_person_leaf_shape_hash(cohort.filters)
        updated = Cohort.objects.filter(
            id=cohort.id,
            team_id=cohort.team_id,
            person_filters_shape_hash__isnull=True,
        ).update(person_filters_shape_hash=person_shape_hash)
        if updated:
            cohort.person_filters_shape_hash = person_shape_hash
        else:
            cohort.refresh_from_db(fields=["person_filters_shape_hash"])

    return cohort.filters_shape_hash or ""


def stamp_events_readiness(run: CohortBackfillRun, cohort_id: int) -> bool:
    """CAS-stamp event readiness for one pinned cohort.

    Keys on the behavioral shape hash, not the full one: edit-time invalidation only nulls
    ``last_backfill_events_at`` when the behavioral leaves change (see ``_maintain_filter_shape_hashes``).
    A person-property or cohort-reference edit mid-backfill shifts the full hash without touching
    events readiness, so keying on the full hash would wrongly supersede a still-valid events backfill.

    This update intentionally bypasses signals. The caller must explicitly invalidate feature-flag
    and behavioral-cohort caches after a successful stamp.

    Call inside a transaction: the cohort stamp and the participation CAS that ratifies it must
    commit or roll back together.
    """
    participation = CohortBackfillRunCohort.objects.for_team(run.team_id).get(run_id=run.id, cohort_id=cohort_id)
    if participation.superseded_at is not None:
        # A superseded participation is terminal. Refuse even when its pinned behavioral hash matches
        # the cohort's current one again (A->B->A edit-revert): the events backfill it covered is gone.
        logger.info("cohort_backfill_readiness_stamp_refused_superseded", run_id=str(run.id), cohort_id=cohort_id)
        return False

    updated = Cohort.objects.filter(
        id=cohort_id,
        team_id=run.team_id,
        behavioral_filters_shape_hash=participation.behavioral_filters_shape_hash,
        last_backfill_events_at__isnull=True,
    ).update(last_backfill_events_at=Now())
    if updated:
        # ``superseded_at__isnull`` guards a supersession racing in after the up-front check; a
        # 0-row stamp then means the participation lost the race, so refuse (finalizer treats it
        # as superseded) rather than claim success.
        stamped = (
            CohortBackfillRunCohort.objects.for_team(run.team_id)
            .filter(id=participation.id, superseded_at__isnull=True)
            .update(stamped_at=Now(), error="")
        )
        if not stamped:
            # The cohort stamp above is this transaction's own uncommitted write, so take it back:
            # leaving it would open ``is_flag_compatible`` on a backfill that just lost the race.
            Cohort.objects.filter(
                id=cohort_id,
                team_id=run.team_id,
                behavioral_filters_shape_hash=participation.behavioral_filters_shape_hash,
            ).update(last_backfill_events_at=None)
        return bool(stamped)

    current_readiness = (
        Cohort.objects.filter(id=cohort_id, team_id=run.team_id)
        .values_list("behavioral_filters_shape_hash", "last_backfill_events_at")
        .first()
    )
    if (
        current_readiness is not None
        and current_readiness[0] == participation.behavioral_filters_shape_hash
        and current_readiness[1] is not None
    ):
        stamped = (
            CohortBackfillRunCohort.objects.for_team(run.team_id)
            .filter(id=participation.id, superseded_at__isnull=True)
            .update(stamped_at=Now(), error="")
        )
        return bool(stamped)

    error = "Cohort definition changed before readiness was stamped"
    # ``superseded_at__isnull`` keeps an earlier supersession's timestamp and message rather than
    # clobbering them with this later, less specific diagnosis (the Rust side COALESCEs for the
    # same reason). Either way the participation ends up terminal.
    CohortBackfillRunCohort.objects.for_team(run.team_id).filter(
        id=participation.id, superseded_at__isnull=True
    ).update(superseded_at=Now(), error=error)
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
