"""Turning realtime on and off for one cohort.

Flags and workflows decide on a cohort's readiness stamps, never on whether the pipeline loads it, so
a cohort that is off must hold no stamp. Both directions clear them, and the finalizer refuses to stamp
a cohort that is off.
"""

from collections.abc import Callable
from functools import partial

from django.db import transaction
from django.utils import timezone

import structlog

from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash
from products.cohorts.backend.backfill.runs import (
    behavioral_backfill_ineligibility_reason,
    person_backfill_ineligibility_reason,
)
from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillTrigger
from products.cohorts.backend.models.cohort import COHORT_REALTIME_SWITCH_FIELDS, Cohort, CohortType
from products.cohorts.backend.models.dependencies import queue_cohort_backfill, supersede_cohort_backfills
from products.cohorts.backend.models.util import get_all_cohort_dependencies
from products.cohorts.backend.realtime_teams import is_processing_team

logger = structlog.get_logger(__name__)

_INELIGIBILITY_REASON = {
    CohortBackfillKind.BEHAVIORAL: behavioral_backfill_ineligibility_reason,
    CohortBackfillKind.PERSON_PROPERTY: person_backfill_ineligibility_reason,
}


class RealtimeTurnOnRefused(ValueError):
    pass


def turn_realtime_on(team_id: int, cohort_id: int, *, can_edit: Callable[[Cohort], bool]) -> list[int]:
    """Turn realtime on for the cohort and every realtime cohort it includes, and queue their backfills.

    Returns the ids it turned on. Raises ``RealtimeTurnOnRefused`` before it writes anything when one
    of them can never be ready, or ``can_edit`` refuses one of them.
    """
    return _turn_on(team_id, cohort_id, can_edit=can_edit, including_cohort=True)


def turn_realtime_on_for_included_cohorts(
    team_id: int, cohort_id: int, *, can_edit: Callable[[Cohort], bool]
) -> list[int]:
    """After an edit of a cohort that is on, turn on the realtime cohorts it now includes.

    Does nothing once the cohort itself is off, so an edit that read the cohort before a turn-off cannot
    undo it.
    """
    return _turn_on(team_id, cohort_id, can_edit=can_edit, including_cohort=False)


def _turn_on(team_id: int, cohort_id: int, *, can_edit: Callable[[Cohort], bool], including_cohort: bool) -> list[int]:
    if not is_processing_team(team_id, fresh=True):
        raise RealtimeTurnOnRefused("Realtime cohorts aren't available for this project.")

    with transaction.atomic():
        # Locked before the traversal, so an edit that adds an included cohort either commits first and is
        # traversed here, or waits for this commit and then finds the cohort on.
        cohort = Cohort.objects.select_for_update(of=("self",)).get(id=cohort_id, team_id=team_id)
        if not including_cohort and not cohort.realtime_enabled:
            return []
        # A static cohort's criteria are a snapshot nothing evaluates, so the cohorts behind it stay as they are.
        ids = {
            nested.id
            for nested in get_all_cohort_dependencies(cohort, stop_traversal_at_static=True)
            if nested.cohort_type == CohortType.REALTIME and not nested.is_static
        }
        if including_cohort:
            ids.add(cohort_id)
        # Past the root, only rows that change are locked, and in id order, because the finalizer locks the
        # cohorts of a team run one at a time in no fixed order.
        turned_on = list(
            Cohort.objects.select_for_update(of=("self",))
            .filter(team_id=team_id, id__in=ids, realtime_enabled_at__isnull=True)
            .order_by("id")
        )

        now = timezone.now()
        for each in turned_on:
            if not can_edit(each):
                raise RealtimeTurnOnRefused(
                    "Realtime can't be turned on, because this cohort includes a cohort you can't edit. "
                    "Ask someone who can edit that cohort to turn realtime on for it first."
                )
            # Nothing maintained this cohort's membership while it was off, so any stamp on it is stale.
            for field in COHORT_REALTIME_SWITCH_FIELDS:
                setattr(each, field, None)
            each.realtime_enabled_at = now
            _refuse_unless_it_can_be_ready(each)

        for each in turned_on:
            ensure_filters_shape_hash(each)
            each.save(update_fields=list(COHORT_REALTIME_SWITCH_FIELDS))
            # The seeder parses trigger kinds, and this cohort's realtime build is new, so it reuses this one.
            for kind in CohortBackfillKind:
                queue_cohort_backfill(each, CohortBackfillTrigger.COHORT_CREATED, kind)

    return [each.id for each in turned_on]


def turn_realtime_off(team_id: int, cohort_id: int) -> bool:
    """Turn realtime off for the cohort, clear its stamps, and supersede its runs. Leaves nested cohorts on.

    Returns whether it was on. Callers check first that nothing reads the cohort's realtime membership.
    """
    with transaction.atomic():
        cohort = Cohort.objects.select_for_update(of=("self",)).get(id=cohort_id, team_id=team_id)
        if not cohort.realtime_enabled:
            return False
        for field in COHORT_REALTIME_SWITCH_FIELDS:
            setattr(cohort, field, None)
        cohort.save(update_fields=list(COHORT_REALTIME_SWITCH_FIELDS))
        for kind in CohortBackfillKind:
            transaction.on_commit(partial(supersede_cohort_backfills, cohort, kind))
    return True


def _refuse_unless_it_can_be_ready(cohort: Cohort) -> None:
    refusal = f"Realtime can't be turned on for cohort '{cohort.name}'"
    if cohort.is_static:
        raise RealtimeTurnOnRefused(f"{refusal}, because it is a static cohort.")
    if cohort.deleted:
        raise RealtimeTurnOnRefused(f"{refusal}, because it is deleted.")
    if cohort.cohort_type != CohortType.REALTIME:
        raise RealtimeTurnOnRefused(f"{refusal}, because its criteria aren't supported in realtime.")
    for kind in cohort._required_backfill_stamps():
        reason = _INELIGIBILITY_REASON[CohortBackfillKind(kind)](cohort)
        if reason is not None:
            logger.info("cohort_realtime_turn_on_refused", cohort_id=cohort.id, team_id=cohort.team_id, reason=reason)
            raise RealtimeTurnOnRefused(f"{refusal}, because PostHog can't prepare one of its criteria in realtime.")
