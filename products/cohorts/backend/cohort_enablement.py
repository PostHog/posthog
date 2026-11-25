"""Turning realtime on and off for one cohort.

Flags and workflows decide on a cohort's readiness stamps, never on whether the pipeline loads it, so
a cohort that is off must hold no stamp. Both directions clear them, and the finalizer refuses to stamp
a cohort that is off.
"""

from collections.abc import Callable, Sequence
from functools import partial
from typing import Literal

from django.db import connection, transaction
from django.utils import timezone

import structlog

from posthog.models.team.team import Team

from products.cohorts.backend.backfill.flag_calls_table import FlagCallsTableUnresolved
from products.cohorts.backend.backfill.pinning import pin_behavioral_run
from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash
from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillTrigger
from products.cohorts.backend.models.cohort import COHORT_REALTIME_SWITCH_FIELDS, Cohort, CohortType
from products.cohorts.backend.models.dependencies import (
    backfill_ineligibility_reason,
    queue_cohort_backfill,
    supersede_cohort_backfills,
)
from products.cohorts.backend.models.util import get_all_cohort_dependencies
from products.cohorts.backend.parity.eligibility import behavioral_history_over_limit
from products.cohorts.backend.parity.tzdates import day_of_instant, resolve_zoneinfo
from products.cohorts.backend.realtime_limits import (
    max_realtime_cohorts,
    max_realtime_history_days,
    realtime_cohorts_used,
)
from products.cohorts.backend.realtime_teams import is_processing_team

logger = structlog.get_logger(__name__)


def flag_calls_table_refusal(cohort: Cohort) -> str | None:
    """Why the cohort's behavioral backfill can't pick the table to read its flag calls from, or None.

    The backfill run makes the same check when it pins its table, and it refuses a cohort that fails it.
    """
    try:
        pin_behavioral_run([cohort], cohort.team)
    except FlagCallsTableUnresolved as error:
        return str(error)
    return None


class RealtimeTurnOnRefused(ValueError):
    pass


class RealtimeLimitReached(RealtimeTurnOnRefused):
    """A turn-on or an edit that the project's plan does not allow."""

    def __init__(
        self, message: str, *, limit: Literal["cohorts", "history_days"], allowed: int, used: int | None = None
    ) -> None:
        super().__init__(message)
        self.limit = limit
        self.allowed = allowed
        self.used = used


def turn_realtime_on(team_id: int, cohort_id: int, *, can_edit: Callable[[Cohort], bool]) -> list[int]:
    """Turn realtime on for the cohort and every realtime cohort it includes, and queue their backfills.

    Returns the ids it turned on. Raises ``RealtimeTurnOnRefused`` before it writes anything when one
    of them can never be ready, or ``can_edit`` refuses one of them, and its subclass ``RealtimeLimitReached``
    when the project's plan doesn't allow them.
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
        # Turn-ons of one team run one at a time, so an edit's turn-on of the cohorts it now includes reads the
        # cohort after a concurrent turn-on commits, and finds it on. A row lock on the cohort would also do that,
        # but it is taken out of id order, so two turn-ons where one includes the other's cohort could deadlock.
        _lock_turn_ons(team_id)
        cohort = Cohort.objects.select_related("team__organization").get(id=cohort_id, team_id=team_id)
        if not including_cohort and not cohort.realtime_enabled:
            return []
        ids = {nested.id for nested in _included_realtime_cohorts(cohort)}
        if including_cohort:
            ids.add(cohort_id)
        # Only rows that change are locked, and in id order, because the finalizer locks the cohorts of a team
        # run one at a time in no fixed order.
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

        # The team's lock is held from this count through the saves below, so two turn-ons, or a turn-on and an
        # edit, can't both take the last slot.
        _refuse_over_plan_limits(cohort.team, taking_slots=turned_on, history_of=turned_on)

        for each in turned_on:
            ensure_filters_shape_hash(each)
            each.save(update_fields=list(COHORT_REALTIME_SWITCH_FIELDS))
            # The seeder rejects trigger kinds it doesn't know. A first build after turning on is a create as far as it
            # is concerned.
            for kind in CohortBackfillKind:
                queue_cohort_backfill(each, CohortBackfillTrigger.COHORT_CREATED, kind)

    return [each.id for each in turned_on]


def refuse_edit_over_plan_limits(cohort: Cohort, *, held_a_slot: bool, can_edit: Callable[[Cohort], bool]) -> None:
    """Refuse an edit that leaves a cohort holding a slot, when the project's plan doesn't allow the result.

    Call it in the transaction that saves the edit. It takes the lock that turn-ons take, so no turn-on or other edit
    can take a slot between its count and the save. The cohort's criteria have to fit the plan's history limit. The
    save turns on the realtime cohorts they include that are off, so each of those needs a slot and has to fit the
    history limit too. When ``can_edit`` refuses one of them, the turn-on after the save refuses them all, so none of
    them is judged. The cohort needs a slot of its own when it held none before the edit, because it was daily, static
    or deleted. Raises ``RealtimeLimitReached``.
    """
    _lock_turn_ons(cohort.team_id)
    turning_on = [nested for nested in _included_realtime_cohorts(cohort) if not nested.realtime_enabled]
    if not all(can_edit(nested) for nested in turning_on):
        turning_on = []
    _refuse_over_plan_limits(
        cohort.team, taking_slots=turning_on if held_a_slot else [cohort, *turning_on], history_of=[cohort, *turning_on]
    )


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


def _lock_turn_ons(team_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"cohort-realtime-turn-on:{team_id}"])


def _included_realtime_cohorts(cohort: Cohort) -> list[Cohort]:
    # A static cohort's criteria are a snapshot nothing evaluates, so the cohorts behind it stay as they are.
    return [
        nested
        for nested in get_all_cohort_dependencies(cohort, stop_traversal_at_static=True)
        if nested.cohort_type == CohortType.REALTIME and not nested.is_static
    ]


def _refuse_over_plan_limits(team: Team, *, taking_slots: Sequence[Cohort], history_of: Sequence[Cohort]) -> None:
    max_days = max_realtime_history_days(team.organization)
    today = day_of_instant(timezone.now(), resolve_zoneinfo(team.timezone))
    for cohort in history_of:
        if behavioral_history_over_limit((cohort.filters or {}).get("properties"), limit_days=max_days, today=today):
            raise RealtimeLimitReached(
                f"Realtime cohorts on your plan can look back at most {max_days} days, and the criteria of cohort "
                f"'{cohort.name}' look back further. Shorten its time range, then try again.",
                limit="history_days",
                allowed=max_days,
            )

    max_cohorts = max_realtime_cohorts(team.organization)
    if max_cohorts is None or not taking_slots:
        return
    used = realtime_cohorts_used(team.id)
    if used + len(taking_slots) > max_cohorts:
        raise RealtimeLimitReached(
            f"Your plan allows realtime for {max_cohorts} cohorts in this project, and it is on for {used}. This "
            f"needs {len(taking_slots)} more. Turn realtime off for cohorts you no longer need, then try again.",
            limit="cohorts",
            allowed=max_cohorts,
            used=used,
        )


def _refuse_unless_it_can_be_ready(cohort: Cohort) -> None:
    refusal = f"Realtime can't be turned on for cohort '{cohort.name}'"
    if cohort.is_static:
        raise RealtimeTurnOnRefused(f"{refusal}, because it is a static cohort.")
    if cohort.deleted:
        raise RealtimeTurnOnRefused(f"{refusal}, because it is deleted.")
    if cohort.cohort_type != CohortType.REALTIME:
        raise RealtimeTurnOnRefused(f"{refusal}, because its criteria aren't supported in realtime.")
    for kind in cohort._required_backfill_stamps():
        backfill_kind = CohortBackfillKind(kind)
        reason = backfill_ineligibility_reason(cohort, backfill_kind)
        if reason is None and backfill_kind == CohortBackfillKind.BEHAVIORAL:
            reason = flag_calls_table_refusal(cohort)
        if reason is not None:
            logger.info("cohort_realtime_turn_on_refused", cohort_id=cohort.id, team_id=cohort.team_id, reason=reason)
            raise RealtimeTurnOnRefused(f"{refusal}, because PostHog can't prepare one of its criteria in realtime.")
