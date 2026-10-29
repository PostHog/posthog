import math
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Any

from posthog.models.flag_evaluations.sql import (
    FLAG_EVALUATIONS_SOURCE_EVENT,
    FLAG_EVALUATIONS_TABLE,
    FLAG_EVALUATIONS_TTL_DAYS,
)
from posthog.models.team.team import Team

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.parity.eligibility import resolve_behavioral_window

# The seeder scans team-local days and includes the oldest day of the window. A team east of UTC starts its day on
# the UTC date before. A scan that starts at most this many days back reads only days that the TTL keeps, in every
# timezone.
_MAX_FLAG_EVALUATIONS_DAYS_BACK = FLAG_EVALUATIONS_TTL_DAYS - 2


class FlagCallsTable(StrEnum):
    EVENTS = "events"
    FLAG_EVALUATIONS = FLAG_EVALUATIONS_TABLE


class FlagCallsTableUnresolved(ValueError):
    pass


def _slides_with_the_boundary(condition: dict[str, Any]) -> bool:
    window = resolve_behavioral_window(condition)
    return window is not None and window.kind != "explicit"


def _days_back(condition: dict[str, Any], team: Team) -> float:
    """How many team-local days before today the seeder's scan for this condition starts."""
    window = resolve_behavioral_window(condition)
    if window is None:
        return math.inf
    if window.kind != "explicit":
        return window.days
    start = condition.get("explicit_datetime")
    if not isinstance(start, str):
        return math.inf
    parsed = datetime.fromisoformat(start)
    start_day = parsed.astimezone(team.timezone_info).date() if parsed.tzinfo else parsed.date()
    return (datetime.now(team.timezone_info).date() - start_day).days


def _can_seed_from_flag_evaluations(cohort: Cohort, conditions: list[dict[str, Any]], team: Team) -> bool:
    # hogql_cohort_query imports posthog.tasks.calculate_cohort, which imports this module through runs.
    from posthog.hogql_queries.hogql_cohort_query import (  # noqa: PLC0415
        FLAG_CALL_READS_COMPILE_ERRORS,
        batch_flag_call_reads,
    )

    try:
        reads = batch_flag_call_reads(cohort, team)
    except FLAG_CALL_READS_COMPILE_ERRORS as error:
        raise FlagCallsTableUnresolved(
            f"The batch query of cohort {cohort.id} does not compile, so the run can't pick the table to read "
            f"its flag calls from: {error}"
        ) from error
    if not (reads.rewrite_enabled and reads.reads_from_events == 0):
        return False
    within_ttl = all(_days_back(condition, team) <= _MAX_FLAG_EVALUATIONS_DAYS_BACK for condition in conditions)
    if reads.only_in_flag_evaluations:
        if not within_ttl:
            raise FlagCallsTableUnresolved(
                f"A flag-call window of cohort {cohort.id} starts before the oldest day flag_evaluations keeps, and "
                "events holds no new flag calls"
            )
        return True
    return within_ttl and all(_slides_with_the_boundary(condition) for condition in conditions)


def pinned_flag_calls_table(
    cohorts: Iterable[Cohort], conditions: Iterable[dict[str, Any]], team: Team
) -> FlagCallsTable:
    """The table cohort-seeder reads `$feature_flag_called` from in a run over these cohorts and their pinned
    conditions.

    One table covers the whole run. It is flag_evaluations only when every cohort with a flag-call condition meets
    all three rules. A cohort without a flag-call condition does not count.

    - The batch calculation reads every flag call of the cohort from flag_evaluations. The seeder then reads the
      same rows as the batch calculation.
    - Every flag-call window starts at most _MAX_FLAG_EVALUATIONS_DAYS_BACK days before today. The seeder fails a
      run that scans a day older than the flag_evaluations TTL.
    - Every flag-call window slides with the run's boundary, unless the organization's flag calls are only in
      flag_evaluations. batch_flag_call_reads checks the window against flag_evaluations as of today, not as of the
      day the seeder scans it. flag_evaluations drops rows after its TTL. A day that a sliding window still needs
      when the seeder scans it is a day that the TTL keeps. The first day of a fixed range can leave
      flag_evaluations before the seeder scans it, while events still holds it. When events holds no new flag calls,
      flag_evaluations is the only table that has any of them.

    Raises FlagCallsTableUnresolved when a cohort's batch query does not compile, or when the organization's flag
    calls are only in flag_evaluations and a flag-call window starts before the oldest day flag_evaluations keeps.
    In an organization whose flag calls are only in flag_evaluations, events would give the cohort an empty
    flag-call history that still counts as backfilled.
    """
    flag_call_conditions: dict[int, list[dict[str, Any]]] = {}
    for condition in conditions:
        if condition["event_name"] == FLAG_EVALUATIONS_SOURCE_EVENT:
            flag_call_conditions.setdefault(condition["cohort_id"], []).append(condition)
    # A list, not a generator, so all() can't stop at a False verdict before a later cohort raises.
    verdicts = [
        _can_seed_from_flag_evaluations(cohort, flag_call_conditions[cohort.id], team)
        for cohort in cohorts
        if cohort.id in flag_call_conditions
    ]
    return FlagCallsTable.FLAG_EVALUATIONS if verdicts and all(verdicts) else FlagCallsTable.EVENTS
