from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_SOURCE_EVENT, FLAG_EVALUATIONS_TABLE
from posthog.models.team.team import Team

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.parity.eligibility import resolve_behavioral_window


class FlagCallsTable(StrEnum):
    EVENTS = "events"
    FLAG_EVALUATIONS = FLAG_EVALUATIONS_TABLE


class FlagCallsTableUnresolved(ValueError):
    pass


def _slides_with_the_boundary(condition: dict[str, Any]) -> bool:
    window = resolve_behavioral_window(condition)
    return window is not None and window.kind != "explicit"


def _reads_flag_evaluations(cohort: Cohort, conditions: list[dict[str, Any]], team: Team) -> bool:
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
    return (
        reads.rewrite_enabled
        and reads.reads_from_events == 0
        and (reads.only_in_flag_evaluations or all(_slides_with_the_boundary(condition) for condition in conditions))
    )


def pinned_flag_calls_table(
    cohorts: Iterable[Cohort], conditions: Iterable[dict[str, Any]], team: Team
) -> FlagCallsTable:
    """The table cohort-seeder reads `$feature_flag_called` from in a run over these cohorts and their pinned
    conditions.

    One table covers the whole run. It is flag_evaluations only when every cohort with a flag-call condition meets
    both rules. A cohort without a flag-call condition does not count.

    - The batch calculation reads every flag call of the cohort from flag_evaluations. The seeder then reads the
      same rows as the batch calculation.
    - Every flag-call window slides with the run's boundary, unless the organization's flag calls are only in
      flag_evaluations. The batch check judges coverage from today. flag_evaluations drops rows after its TTL. A
      day that a sliding window still needs when the seeder scans it is a day that the TTL keeps. The first day of a
      fixed range can leave flag_evaluations before the seeder scans it, while events still holds it. When events
      holds no new flag calls, flag_evaluations is the only table that has any of them.

    Raises FlagCallsTableUnresolved when a cohort's batch query does not compile. In an organization whose flag calls
    are only in flag_evaluations, events would give the cohort an empty flag-call history that still counts as
    backfilled.
    """
    flag_call_conditions: dict[int, list[dict[str, Any]]] = {}
    for condition in conditions:
        if condition["event_name"] == FLAG_EVALUATIONS_SOURCE_EVENT:
            flag_call_conditions.setdefault(condition["cohort_id"], []).append(condition)
    # A list, not a generator, so every cohort compiles and a compile error does not depend on the cohort order.
    verdicts = [
        _reads_flag_evaluations(cohort, flag_call_conditions[cohort.id], team)
        for cohort in cohorts
        if cohort.id in flag_call_conditions
    ]
    return FlagCallsTable.FLAG_EVALUATIONS if verdicts and all(verdicts) else FlagCallsTable.EVENTS
