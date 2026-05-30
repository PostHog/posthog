"""Pre-aggregated retention base query (per-person curve).

Produces a SelectQuery in the same shape `RetentionFixedIntervalBaseQueryBuilder` emits, but
reads one row per person from `retention_curve` instead of scanning events. Each curve row
holds `first_seen_day` (all-history) + `active_offsets` (day-offsets active since then), so
we reconstruct the per-person array of start-of-interval datetimes the legacy builder derives
from raw events, then reuse the legacy builder's helpers to compute `start_interval_index`
and `intervals_from_base`.

Scope (gate-enforced): first-occurrence retention (`retention_first_time` /
`retention_first_ever_occurrence`) for page-view or all-events, both entities the same kind.
Because `first_seen_day` is the all-history first day, the cohort anchor is exact — the
"looks-new-but-isn't" error a windowed materialisation hits does not apply here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.insights.retention.retention_curve_materialize import kind_for_entity_id

if TYPE_CHECKING:
    from posthog.hogql_queries.insights.retention.retention_base_query_fixed import (
        RetentionFixedIntervalBaseQueryBuilder,
    )

PREAGG_TABLE = "retention_curve"

# Verbatim from RetentionFixedIntervalBaseQueryBuilder.build_base_query — the exploded,
# 0-based cohort interval index. Reused as-is so the pre-agg path matches the legacy path;
# `is_valid_start_interval` is injected (first-occurrence: `_start_event_timestamps[1] =
# interval_date`).
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


def build_preagg_base_query(builder: RetentionFixedIntervalBaseQueryBuilder) -> ast.SelectQuery:
    runner = builder.runner
    kind = kind_for_entity_id(runner.start_event.id)

    # Per-person active intervals: map each day-offset to first_seen_day + offset, truncate to
    # the query interval (day/week/month, team tz), dedupe + sort. Several day-offsets in the
    # same week/month collapse to one — correct per-person rollup. Used as BOTH start and
    # return timestamps (same kind, gate-enforced).
    interval_of_offset = runner.query_date_range.get_start_of_interval_hogql(
        source=parse_expr("first_seen_day + toIntervalDay(off)")
    )
    active_intervals = parse_expr(
        "arraySort(arrayDistinct(arrayMap(off -> {interval_of_offset}, active_offsets)))",
        {"interval_of_offset": interval_of_offset},
    )

    is_valid_start_interval = builder._is_valid_start_interval_expr("_start_event_timestamps")
    intervals_from_base_expr, _retention_value_expr = builder._get_intervals_from_base_exprs()

    # FINAL is disallowed in HogQL, so dedupe the ReplacingMergeTree rows explicitly: keep the
    # newest (max computed_at) row per person, then filter the cohort window on the deduped
    # first_seen_day in the outer query.
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
                person_id AS actor_id,
                argMax(first_seen_day, computed_at) AS first_seen_day,
                argMax(active_offsets, computed_at) AS active_offsets
            FROM posthog.retention_curve
            WHERE team_id = {team_id} AND kind = {kind}
            GROUP BY person_id
        )
        WHERE first_seen_day >= {first_seen_lower}
            AND first_seen_day < {first_seen_upper}
        """,
        placeholders={
            "start_event_timestamps": active_intervals,
            "date_range": builder._date_range_alias().expr,
            "return_event_timestamps": active_intervals,
            "start_interval_index": parse_expr(
                _START_INTERVAL_INDEX_SQL, {"is_valid_start_interval": is_valid_start_interval}
            ),
            "intervals_from_base": intervals_from_base_expr,
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
