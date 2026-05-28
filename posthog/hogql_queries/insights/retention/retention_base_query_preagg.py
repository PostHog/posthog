"""
Pre-aggregated retention base query.

Produces a SelectQuery in the same shape `build_base_query_legacy` emits, but
reads from `retention_actor_event_day` instead of `events`. The pre-agg table
already has one row per (team_id, day, actor_id, event) with `min(timestamp)` as
`first_ts`, so the array aggregates the legacy path runs over raw events
(`arraySort(groupUniqArrayIf(toStartOfInterval(events.timestamp, ...), ...))`)
become equivalent aggregates over the pre-agg rows.

v1 routing gate only — same constraints documented in
`.planning/retention-preagg-implementation-plan.md`:

- recurring OR first-occurrence-matching-filters (NOT first-ever)
- person retention (not group)
- no entity-property filter
- no property aggregation
- minimum_occurrences == 1

Anything outside that envelope must fall through to the raw events path.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

if TYPE_CHECKING:
    from posthog.hogql_queries.insights.retention.retention_base_query_fixed import (
        RetentionFixedIntervalBaseQueryBuilder,
    )

PREAGG_TABLE = "retention_actor_event_day"


def build_preagg_base_query(
    builder: RetentionFixedIntervalBaseQueryBuilder,
    job_ids: list[uuid.UUID],
) -> ast.SelectQuery:
    """Equivalent retention base query reading from `retention_actor_event_day`.

    `builder` provides access to the same `query_date_range`, entity selection,
    and outer retention math the legacy path uses. Only the inner-most aggregation
    (the per-actor array of qualifying interval starts) is replaced with reads
    against the pre-agg table.
    """
    runner = builder.runner

    # Source field for "did this happen during interval X". On the legacy path
    # this is `events.timestamp`; on pre-agg it's the materialised `first_ts`.
    start_of_interval_sql = runner.query_date_range.get_start_of_interval_hogql(
        source=ast.Field(chain=[PREAGG_TABLE, "first_ts"]),
    )

    # Entity predicates: pre-agg has the `event` column directly, no table prefix needed.
    # v1 gate excludes entity-property filters, so this is just a string-event comparison.
    start_entity_expr = _entity_event_filter(runner.start_event)
    return_entity_expr = _entity_event_filter(runner.return_event)

    # Day-range filter on pre-agg's `day` column. The legacy path filters
    # `events.timestamp >= date_from AND events.timestamp < date_to`; the
    # pre-agg equivalent filters by daily bucket.
    day_range_filter = _day_range_filter(runner)

    # Array aggregates — same shape as build_base_query_legacy, just reading
    # over pre-agg rows.
    start_event_timestamps_expr = parse_expr(
        """
        arraySort(
            groupUniqArrayIf(
                {start_of_interval_sql},
                {start_entity_expr} and {day_range_filter}
            )
        )
        """,
        {
            "start_of_interval_sql": start_of_interval_sql,
            "start_entity_expr": start_entity_expr,
            "day_range_filter": day_range_filter,
        },
    )

    # First-occurrence wrap. For first-time queries, only keep the actor's
    # `start_event_timestamps` if their min timestamp falls in the cohort window.
    # Matches the legacy path's wrapper but uses pre-agg's first_ts column. v1 gate
    # excludes first-ever (which needs all-time lookback the pre-agg doesn't have)
    # and entity property filters (so the entity expr is the simple event-name match).
    if runner.is_first_occurrence_matching_filters:
        min_timestamp_inner_expr = parse_expr(
            "minIf({ts}, {expr})",
            {
                "ts": ast.Field(chain=[PREAGG_TABLE, "first_ts"]),
                "expr": start_entity_expr,
            },
        )
        start_event_timestamps_expr = parse_expr(
            """
            if(
                has(
                    {start_event_timestamps} as _start_event_timestamps,
                    {min_timestamp}
                ),
                _start_event_timestamps,
                []
            )
            """,
            {
                "start_event_timestamps": start_event_timestamps_expr,
                "min_timestamp": runner.query_date_range.date_to_start_of_interval_hogql(min_timestamp_inner_expr),
            },
        )

    return_event_timestamps_expr = parse_expr(
        """
        arraySort(
            groupUniqArrayIf(
                {start_of_interval_sql},
                {return_entity_expr} and {day_range_filter}
            )
        )
        """,
        {
            "start_of_interval_sql": start_of_interval_sql,
            "return_entity_expr": return_entity_expr,
            "day_range_filter": day_range_filter,
        },
    )

    # The downstream array math (start_interval_index, intervals_from_base) operates
    # on the internal aliases (_start_event_timestamps, date_range, start_event_timestamps)
    # rather than on events.* directly, so we reuse the builder's helpers verbatim.
    is_valid_start_interval = builder._is_valid_start_interval_expr("_start_event_timestamps")
    intervals_from_base_expr, _retention_value_expr = builder._get_intervals_from_base_exprs()

    select_fields: list[ast.Expr] = [
        ast.Alias(
            alias="actor_id",
            expr=ast.Field(chain=[PREAGG_TABLE, "actor_id"]),
        ),
        ast.Alias(alias="start_event_timestamps", expr=start_event_timestamps_expr),
        builder._date_range_alias(),
        ast.Alias(alias="return_event_timestamps", expr=return_event_timestamps_expr),
        ast.Alias(
            alias="start_interval_index",
            expr=parse_expr(
                """
                arrayJoin(
                    arrayFilter(
                        x -> x > -1,
                        arrayMap(
                            (interval_index, interval_date, _start_event_timestamps) ->
                                if({is_valid_start_interval}, interval_index - 1, -1),
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
                """,
                {"is_valid_start_interval": is_valid_start_interval},
            ),
        ),
        ast.Alias(alias="intervals_from_base", expr=intervals_from_base_expr),
    ]

    # WHERE: scope to this team's materialised rows. team_id is also needed so the
    # MergeTree ordering key prunes parts; job_id IN (...) ensures we only read the
    # latest materialisation set for this query.
    where_filters: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[PREAGG_TABLE, "team_id"]),
            right=ast.Constant(value=runner.team.pk),
        ),
        _job_id_filter(job_ids),
        # Pre-event-name filter mirrors the legacy path's `event IN (start, return)` pre-filter.
        # Lets ClickHouse skip rows for events the read doesn't care about.
        _event_in_filter(runner),
    ]

    return ast.SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=[PREAGG_TABLE])),
        where=ast.And(exprs=where_filters),
        group_by=[ast.Field(chain=["actor_id"])],
        having=ast.And(exprs=[ast.Constant(value=1)]),
    )


def _entity_event_filter(entity) -> ast.Expr:
    """Build `event = '<name>'` for a RetentionEntity. v1 gate excludes actions and
    entity-property filters, so this only handles raw event names and the "all events"
    case (entity.id is None)."""
    if entity.id is None:
        return ast.Constant(value=True)
    return parse_expr(
        "{table_event_field} = {event_name}",
        {
            "table_event_field": ast.Field(chain=[PREAGG_TABLE, "event"]),
            "event_name": ast.Constant(value=entity.id),
        },
    )


def _day_range_filter(runner) -> ast.Expr:
    """Filter pre-agg rows by daily bucket for the cohort window. The legacy path
    filters `events.timestamp` directly; here we filter the materialised `day`."""
    return ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=[PREAGG_TABLE, "day"]),
                right=ast.Call(
                    name="toDate",
                    args=[runner.query_date_range.date_from_to_start_of_interval_hogql()],
                ),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=[PREAGG_TABLE, "day"]),
                right=ast.Call(
                    name="toDate",
                    args=[ast.Constant(value=runner.query_date_range.date_to())],
                ),
            ),
        ]
    )


def _event_in_filter(runner) -> ast.Expr:
    """Pre-filter pre-agg rows by event name. Mirrors the legacy path's
    `event IN (start, return)` filter so we read only relevant rows."""
    events_for_entity = runner.get_events_for_entity(runner.start_event) + runner.get_events_for_entity(
        runner.return_event
    )
    unique_events = {e for e in events_for_entity if e is not None}
    if not unique_events:
        # One of the entities is "all events" — no pre-filter.
        return ast.Constant(value=True)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=[PREAGG_TABLE, "event"]),
        right=ast.Tuple(exprs=[ast.Constant(value=event) for event in sorted(unique_events)]),
    )


def _job_id_filter(job_ids: list[uuid.UUID]) -> ast.Expr:
    """Filter pre-agg rows to the latest materialisation set for this query.
    `ensure_precomputed` returns one job_id per (team, day) covered by the cohort window."""
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=[PREAGG_TABLE, "job_id"]),
        right=ast.Tuple(exprs=[ast.Constant(value=str(jid)) for jid in job_ids]),
    )
