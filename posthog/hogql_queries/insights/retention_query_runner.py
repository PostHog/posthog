from datetime import datetime, timedelta
from posthog.hogql.property import property_to_expr
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.constants import HogQLGlobalSettings, MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY
from math import ceil
from typing import Any
from typing import Optional

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.constants import (
    TREND_FILTER_TYPE_EVENTS,
    RetentionQueryType,
)
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import entity_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.models.action.action import Action
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRangeWithIntervals
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.util import correct_result_for_sampling
from posthog.schema import (
    CachedRetentionQueryResponse,
    HogQLQueryModifiers,
    RetentionQueryResponse,
    IntervalType,
    RetentionEntity,
    EntityType,
)
from posthog.schema import RetentionQuery, RetentionType

DEFAULT_INTERVAL = IntervalType("day")
DEFAULT_TOTAL_INTERVALS = 11

DEFAULT_ENTITY = RetentionEntity(
    **{
        "id": "$pageview",
        "type": TREND_FILTER_TYPE_EVENTS,
    }
)


class RetentionQueryRunner(QueryRunner):
    query: RetentionQuery
    response: RetentionQueryResponse
    cached_response: CachedRetentionQueryResponse
    target_entity: RetentionEntity
    returning_entity: RetentionEntity

    def __init__(
        self,
        query: RetentionQuery | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

        self.target_entity = self.query.retentionFilter.targetEntity or DEFAULT_ENTITY
        self.returning_entity = self.query.retentionFilter.returningEntity or DEFAULT_ENTITY

    @property
    def group_type_index(self) -> int | None:
        return self.query.aggregation_group_type_index

    def filter_timestamp(self) -> ast.Expr:
        field_to_compare = ast.Field(chain=["events", "timestamp"])
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=field_to_compare,
                    right=self.query_date_range.get_start_of_interval_hogql(),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=field_to_compare,
                    right=ast.Constant(value=self.query_date_range.date_to()),
                ),
            ]
        )

    def _get_events_for_entity(self, entity: RetentionEntity) -> list[str | None]:
        if entity.type == EntityType.ACTIONS and entity.id:
            action = Action.objects.get(pk=int(entity.id))
            return action.get_step_events()
        return [entity.id] if isinstance(entity.id, str) else [None]

    def events_where_clause(self, event_query_type: RetentionQueryType):
        events_where = []

        if self.query.properties is not None and self.query.properties != []:
            events_where.append(property_to_expr(self.query.properties, self.team))

        if (
            self.query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for prop in self.team.test_account_filters:
                events_where.append(property_to_expr(prop, self.team))

        if event_query_type == RetentionQueryType.TARGET:
            # when it's recurring, we only have to grab events for the period, rather than events for all time
            events_where.append(self.filter_timestamp())

        # Pre filter event
        events = self._get_events_for_entity(self.target_entity) + self._get_events_for_entity(self.returning_entity)
        # Don't pre-filtering if any of them is "All events"
        if None not in events:
            events_where.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["event"]),
                    # Sorting for consistent snapshots in tests
                    right=ast.Tuple(exprs=[ast.Constant(value=event) for event in sorted(events)]),  # type: ignore
                    op=ast.CompareOperationOp.In,
                )
            )

        return events_where

    def actor_query(self, breakdown_values_filter: Optional[int] = None) -> ast.SelectQuery:
        start_of_interval_sql = self.query_date_range.get_start_of_interval_hogql(
            source=ast.Field(chain=["events", "timestamp"])
        )

        event_query_type = (
            RetentionQueryType.TARGET_FIRST_TIME
            if self.query.retentionFilter.retentionType == RetentionType.RETENTION_FIRST_TIME
            else RetentionQueryType.TARGET
        )

        target_entity_expr = entity_to_expr(self.target_entity)
        event_filters = self.events_where_clause(event_query_type)

        target_timestamps = parse_expr(
            """
            arraySort(
                groupUniqArrayIf(
                    {start_of_interval_sql},
                    {target_entity_expr} and
                    {filter_timestamp}
                )
            )
            """,
            {
                "start_of_interval_sql": start_of_interval_sql,
                "target_entity_expr": target_entity_expr,
                "filter_timestamp": self.filter_timestamp(),
            },
        )

        if event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
            target_timestamps = parse_expr(
                """
                    if(
                        has(
                            {target_timestamps} as _target_timestamps,
                            {min_timestamp}
                        ),
                        _target_timestamps,
                        []
                    )
                """,
                {
                    "target_timestamps": target_timestamps,
                    "min_timestamp": self.query_date_range.date_to_start_of_interval_hogql(
                        parse_expr(
                            "minIf(events.timestamp, {target_entity_expr})",
                            {
                                "target_entity_expr": target_entity_expr,
                            },
                        )
                    ),
                },
            )
            is_in_breakdown_value = parse_expr("target_timestamps[1] = breakdown_value_timestamp")
            is_first_intervals_from_base = parse_expr("target_timestamps[1] = date_range[breakdown_values + 1]")
        else:
            is_in_breakdown_value = parse_expr("has(target_timestamps, breakdown_value_timestamp)")
            is_first_intervals_from_base = parse_expr("has(target_timestamps, date_range[breakdown_values + 1])")

        target_field = "person_id"
        if self.group_type_index is not None:
            group_index = int(self.group_type_index)
            if 0 <= group_index <= 4:
                target_field = f"$group_{group_index}"

                event_filters.append(
                    ast.Not(
                        expr=ast.Call(
                            name="has",
                            args=[
                                ast.Array(exprs=[ast.Constant(value="")]),
                                ast.Field(chain=["events", f"$group_{self.group_type_index}"]),
                            ],
                        ),
                    ),
                )

        inner_query = ast.SelectQuery(
            select=[
                ast.Alias(alias="actor_id", expr=ast.Field(chain=["events", target_field])),
                ast.Alias(alias="target_timestamps", expr=target_timestamps),
                ast.Alias(
                    alias="returning_timestamps",
                    expr=parse_expr(
                        """
                    arraySort(
                        groupUniqArrayIf(
                            {start_of_interval_timestamp},
                            {returning_entity_expr}
                        )
                    )
                """,
                        {
                            "start_of_interval_timestamp": start_of_interval_sql,
                            "returning_entity_expr": entity_to_expr(self.returning_entity),
                        },
                    ),
                ),
                ast.Alias(
                    alias="date_range",
                    expr=parse_expr(
                        """
                        arrayMap(
                            x -> {date_from_start_of_interval} + {to_interval_function},
                            range(0, {total_intervals})
                        )
                    """,
                        {
                            "total_intervals": ast.Constant(value=self.query_date_range.total_intervals),
                            "date_from_start_of_interval": self.query_date_range.date_from_to_start_of_interval_hogql(),
                            "to_interval_function": ast.Call(
                                name=f"toInterval{self.query_date_range.interval_name.capitalize()}",
                                args=[ast.Field(chain=["x"])],
                            ),
                        },
                    ),
                ),
                ast.Alias(
                    alias="breakdown_values",
                    expr=parse_expr(
                        """
                        arrayJoin(
                            arrayFilter(
                                x -> x > -1,
                                arrayMap(
                                (_breakdown_value, breakdown_value_timestamp) ->
                                    if(
                                        {is_in_breakdown_value},
                                        _breakdown_value - 1,
                                        -1
                                    ),
                                    arrayEnumerate(date_range),
                                    date_range
                                )
                            )
                        )
                    """,
                        {"is_in_breakdown_value": is_in_breakdown_value},
                    ),
                ),
                ast.Alias(
                    alias="intervals_from_base",
                    expr=parse_expr(
                        """
                    arrayJoin(
                        arrayConcat(
                            if(
                                {is_first_interval_from_base},
                                [0],
                                []
                            ),
                            arrayFilter(
                                x -> x > 0, -- first match always comes from target_timestamps, hence not -1 here
                                arrayMap(
                                    _timestamp ->
                                        indexOf(arraySlice(date_range, breakdown_values + 1), _timestamp) - 1
                                    , returning_timestamps
                                )
                            )
                        )
                    )
                    """,
                        {"is_first_interval_from_base": is_first_intervals_from_base},
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=event_filters),
            group_by=[ast.Field(chain=["actor_id"])],
            having=(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["breakdown_values"]),
                    right=ast.Constant(value=breakdown_values_filter),
                )
                if breakdown_values_filter is not None
                else None
            ),
        )
        if self.query.samplingFactor is not None and isinstance(self.query.samplingFactor, float):
            inner_query.select_from.sample = ast.SampleExpr(
                sample_value=ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor))
            )

        return inner_query

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        placeholders = {
            "actor_query": self.actor_query(),
        }

        with self.timings.measure("retention_query"):
            retention_query = parse_select(
                """
                    SELECT [actor_activity.breakdown_values]       AS breakdown_values,
                           actor_activity.intervals_from_base      AS intervals_from_base,
                           COUNT(DISTINCT actor_activity.actor_id) AS count

                    FROM {actor_query} AS actor_activity

                    GROUP BY breakdown_values,
                             intervals_from_base

                    ORDER BY breakdown_values,
                             intervals_from_base

                    LIMIT 10000
                """,
                placeholders,
                timings=self.timings,
            )
        return retention_query

    @cached_property
    def query_date_range(self) -> QueryDateRangeWithIntervals:
        total_intervals = self.query.retentionFilter.totalIntervals or DEFAULT_TOTAL_INTERVALS
        interval = (
            IntervalType(self.query.retentionFilter.period.lower())
            if self.query.retentionFilter.period
            else DEFAULT_INTERVAL
        )

        return QueryDateRangeWithIntervals(
            date_range=self.query.dateRange,
            total_intervals=total_intervals,
            team=self.team,
            interval=interval,
            now=datetime.now(),
        )

    def _refresh_frequency(self):
        date_to = self.query_date_range.date_to()
        date_from = self.query_date_range.date_from()
        interval = self.query_date_range.interval_name

        delta_days: Optional[int] = None
        if date_from and date_to:
            delta = date_to - date_from
            delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

        refresh_frequency = BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            # The interval is shorter for short-term insights
            refresh_frequency = REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return refresh_frequency

    def get_date(self, first_interval):
        date = self.query_date_range.date_from() + self.query_date_range.determine_time_delta(
            first_interval, self.query_date_range.interval_name.title()
        )
        if self.query_date_range.interval_type == IntervalType.HOUR:
            utfoffset = self.team.timezone_info.utcoffset(date)
            if utfoffset is not None:
                date = date + utfoffset
        return date

    def calculate(self) -> RetentionQueryResponse:
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="RetentionQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            settings=HogQLGlobalSettings(max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY),
        )

        result_dict = {
            (tuple(breakdown_values), intervals_from_base): {
                "count": correct_result_for_sampling(count, self.query.samplingFactor),
            }
            for (breakdown_values, intervals_from_base, count) in response.results
        }
        results = [
            {
                "values": [
                    result_dict.get(((first_interval,), return_interval), {"count": 0})
                    for return_interval in range(self.query_date_range.total_intervals - first_interval)
                ],
                "label": f"{self.query_date_range.interval_name.title()} {first_interval}",
                "date": self.get_date(first_interval),
            }
            for first_interval in range(self.query_date_range.total_intervals)
        ]

        return RetentionQueryResponse(results=results, timings=response.timings, hogql=hogql, modifiers=self.modifiers)

    def to_actors_query(self, interval: Optional[int] = None) -> ast.SelectQuery:
        with self.timings.measure("retention_query"):
            retention_query = parse_select(
                """
                    SELECT
                        actor_id,
                        groupArray(actor_activity.intervals_from_base) AS appearance_intervals,
                        arraySort(appearance_intervals) AS appearances

                    FROM {actor_query} AS actor_activity

                    GROUP BY actor_id
                """,
                placeholders={
                    "actor_query": self.actor_query(breakdown_values_filter=interval),
                },
                timings=self.timings,
            )
            # We want to expose each interval as a separate column
            for i in range(self.query_date_range.total_intervals - interval):
                retention_query.select.append(
                    ast.Alias(
                        alias=f"{self.query_date_range.interval_name}_{i}",
                        expr=ast.Call(
                            name="arrayExists",
                            args=[
                                ast.Lambda(
                                    args=["x"],
                                    expr=ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["x"]),
                                        right=ast.Constant(value=i),
                                    ),
                                ),
                                ast.Field(chain=["appearance_intervals"]),
                            ],
                        ),
                    )
                )
        return retention_query
