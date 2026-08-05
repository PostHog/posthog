"""Shape-hash maintenance and the CAS that opens a cohort's readiness for flag targeting.

Both ``stamp_*_readiness`` functions share one contract. They intentionally bypass signals, so the
caller must explicitly invalidate the feature-flag and behavioral-cohort caches after a successful
stamp; and they must be called inside a transaction, because the cohort stamp and the participation
CAS that ratifies it have to commit or roll back together.
"""

from dataclasses import dataclass
from uuid import UUID

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


@dataclass(frozen=True)
class _ReadinessSpec:
    """The columns one backfill kind's readiness stamp keys on.

    ``hash_field`` names the same column on both models: the fingerprint the run pinned on the
    participation, and the cohort's current one it is CAS'd against.

    ``readiness`` names the stamped column, not the run kind, and the log field it feeds is named
    for it. Deliberately not the ``CohortBackfillKind`` vocabulary the metrics label ``kind`` with:
    a behavioral run stamps ``last_backfill_events_at``, so one value would have to be wrong.
    """

    readiness: str
    hash_field: str
    stamp_field: str


_EVENTS = _ReadinessSpec(
    readiness="events",
    hash_field="behavioral_filters_shape_hash",
    stamp_field="last_backfill_events_at",
)

_PERSON_PROPERTIES = _ReadinessSpec(
    readiness="person_properties",
    hash_field="person_filters_shape_hash",
    stamp_field="last_backfill_person_properties_at",
)


def stamp_events_readiness(run: CohortBackfillRun, cohort_id: int) -> bool:
    """CAS-stamp event readiness for one pinned cohort.

    Keys on the behavioral shape hash, not the full one: edit-time invalidation only nulls
    ``last_backfill_events_at`` when the behavioral leaves change (see ``_maintain_filter_shape_hashes``).
    A person-property or cohort-reference edit mid-backfill shifts the full hash without touching
    events readiness, so keying on the full hash would wrongly supersede a still-valid events backfill.
    """
    return _stamp_readiness(run, cohort_id, _EVENTS)


def stamp_person_properties_readiness(run: CohortBackfillRun, cohort_id: int) -> bool:
    """CAS-stamp person-property readiness for one pinned cohort.

    The mirror of :func:`stamp_events_readiness`, keyed on the person shape hash so a behavioral
    edit mid-backfill cannot supersede a still-valid person backfill.

    The stamp asserts the cohort's person properties were backfilled as far back as the run's pinned
    ``person_scan_since`` horizon, not over all history: a person who last changed before that
    horizon and has produced nothing since is outside what the run scanned.
    """
    return _stamp_readiness(run, cohort_id, _PERSON_PROPERTIES)


def _stamp_readiness(run: CohortBackfillRun, cohort_id: int, spec: _ReadinessSpec) -> bool:
    """The kind-agnostic stamp protocol behind the two public wrappers."""
    participation = CohortBackfillRunCohort.objects.for_team(run.team_id).get(run_id=run.id, cohort_id=cohort_id)
    if participation.superseded_at is not None:
        # A superseded participation is terminal. Refuse even when its pinned hash matches the
        # cohort's current one again (A->B->A edit-revert): the backfill it covered is gone.
        logger.info(
            "cohort_backfill_readiness_stamp_refused_superseded",
            run_id=str(run.id),
            cohort_id=cohort_id,
            readiness=spec.readiness,
        )
        return False

    pinned = getattr(participation, spec.hash_field)
    # Reused by the rollback below, so both writes fence on the same pinned fingerprint.
    cohort_fence = {"id": cohort_id, "team_id": run.team_id, spec.hash_field: pinned}

    updated = Cohort.objects.filter(**cohort_fence, **{f"{spec.stamp_field}__isnull": True}).update(
        **{spec.stamp_field: Now()}
    )
    if updated:
        # ``superseded_at__isnull`` guards a supersession racing in after the up-front check; a
        # 0-row stamp then means the participation lost the race, so refuse (finalizer treats it
        # as superseded) rather than claim success.
        stamped = _ratify(run, participation.id)
        if not stamped:
            # The cohort stamp above is this transaction's own uncommitted write, so take it back:
            # leaving it would open ``is_flag_compatible`` on a backfill that just lost the race.
            Cohort.objects.filter(**cohort_fence).update(**{spec.stamp_field: None})
        return stamped

    current_readiness = (
        Cohort.objects.filter(id=cohort_id, team_id=run.team_id).values_list(spec.hash_field, spec.stamp_field).first()
    )
    if current_readiness is not None and current_readiness[0] == pinned and current_readiness[1] is not None:
        return _ratify(run, participation.id)

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
    logger.info(
        "cohort_backfill_readiness_stamp_superseded",
        run_id=str(run.id),
        cohort_id=cohort_id,
        readiness=spec.readiness,
    )
    return False


def _ratify(run: CohortBackfillRun, participation_id: UUID) -> bool:
    """Mark the participation as the one that earned the cohort's stamp, unless it lost the race."""
    return bool(
        CohortBackfillRunCohort.objects.for_team(run.team_id)
        .filter(id=participation_id, superseded_at__isnull=True)
        .update(stamped_at=Now(), error="")
    )
