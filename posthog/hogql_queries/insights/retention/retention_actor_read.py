"""Pre-aggregated retention base query (per-actor `retention_actor` table).

Produces a SelectQuery in the same shape `RetentionFixedIntervalBaseQueryBuilder` emits, but
reads one row per actor from `retention_actor` instead of scanning events. Each actor's
`active_days` (a `groupUniqArray` set-state of absolute team-tz day-numbers, horizon-capped
from their first day) is merged at read, mapped back to dates, truncated to the query interval,
and reused as BOTH the start and return interval set — then the legacy builder's helpers
compute `start_interval_index` and `intervals_from_base`.

The cohort anchor is `arrayMin(active_days)` — the actor's all-history first qualifying day.
Because the horizon cap is taken from that first day, the first day is always present in the
set, so `arrayMin` equals the all-history first occurrence exactly (no "looks-new-but-isn't"
boundary error). `first_seen` (the minState column) is reserved for merge resolution and is not
needed here.

Scope (gate-enforced): first-occurrence retention for page-view or all-events, both entities
the same kind, no event-property filters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.insights.retention.retention_actor_materialize import kind_for_entity_id

if TYPE_CHECKING:
    from posthog.hogql_queries.insights.retention.retention_base_query_fixed import (
        RetentionFixedIntervalBaseQueryBuilder,
    )

# Verbatim from RetentionFixedIntervalBaseQueryBuilder — the exploded, 0-based cohort interval
# index. Reused as-is so the pre-agg path matches the legacy path; `is_valid_start_interval` is
# injected (first-occurrence: `_start_event_timestamps[1] = interval_date`).
_START_INTERVAL_INDEX_SQL = """
arrayJoin(
    arrayFilter(
        x -> x > -1,
        arrayMap(
            (interval_index, interval_date, _start_event_timestamps) ->
                if(
                    {is_valid_start_interval},
                    interval_index - 1,
                    -1
                ),
            arrayEnumerate(date_range),
            date_range,
            arrayResize(
                [start_event_timestamps],
                length(date_range),
                start_event_timestamps
            )
        )
    )
)
"""

# Absolute day-number -> Date. toDate has no integer overload in HogQL, so reconstruct via
# Date + interval arithmetic from the epoch (day-numbers are days since 1970-01-01).
_DATE_OF_DAYNUM = "toDate('1970-01-01') + toIntervalDay({daynum})"


def build_preagg_base_query(builder: RetentionFixedIntervalBaseQueryBuilder) -> ast.SelectQuery:
    runner = builder.runner
    kind = kind_for_entity_id(runner.start_event.id)

    # Per-actor active intervals: map each active day-number to its Date, truncate to the query
    # interval (day/week/month, team tz), dedupe + sort. Several days in the same week/month
    # collapse to one — correct per-actor rollup. Used as BOTH start and return timestamps.
    interval_of_daynum = runner.query_date_range.get_start_of_interval_hogql(
        source=parse_expr(_DATE_OF_DAYNUM, {"daynum": ast.Field(chain=["dn"])})
    )
    active_intervals = parse_expr(
        "arraySort(arrayDistinct(arrayMap(dn -> {interval_of_daynum}, day_nums)))",
        {"interval_of_daynum": interval_of_daynum},
    )

    # Cohort anchor day = the actor's first active day-number, as a Date.
    first_seen_day = parse_expr(_DATE_OF_DAYNUM, {"daynum": parse_expr("arrayMin(day_nums)")})

    is_valid_start_interval = builder._is_valid_start_interval_expr("_start_event_timestamps")
    intervals_from_base_expr, _retention_value_expr = builder._get_intervals_from_base_exprs()

    select_query = parse_select(
        """
        SELECT
            actor_id,
            {start_event_timestamps} AS start_event_timestamps,
            {date_range} AS date_range,
            {return_event_timestamps} AS return_event_timestamps,
            {start_interval_index} AS start_interval_index,
            {intervals_from_base} AS intervals_from_base
        FROM (
            SELECT
                actor_id,
                groupUniqArrayMerge(active_days) AS day_nums
            FROM posthog.retention_actor
            WHERE team_id = {team_id} AND kind = {kind}
            GROUP BY actor_id
        )
        WHERE {first_seen_day} >= {first_seen_lower}
            AND {first_seen_day} < {first_seen_upper}
        """,
        placeholders={
            "start_event_timestamps": active_intervals,
            "date_range": builder._date_range_alias().expr,
            "return_event_timestamps": active_intervals,
            "start_interval_index": parse_expr(
                _START_INTERVAL_INDEX_SQL, {"is_valid_start_interval": is_valid_start_interval}
            ),
            "intervals_from_base": intervals_from_base_expr,
            "first_seen_day": first_seen_day,
            "team_id": ast.Constant(value=runner.team.pk),
            "kind": ast.Constant(value=kind),
            "first_seen_lower": ast.Call(
                name="toDate", args=[runner.query_date_range.date_from_to_start_of_interval_hogql()]
            ),
            "first_seen_upper": ast.Call(name="toDate", args=[ast.Constant(value=runner.query_date_range.date_to())]),
        },
    )
    assert isinstance(select_query, ast.SelectQuery)
    return select_query
