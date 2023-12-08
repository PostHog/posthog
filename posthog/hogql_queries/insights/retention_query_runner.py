from datetime import datetime, timedelta
from math import ceil
from typing import Any, Dict
from typing import Optional

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.caching.utils import is_stale
from posthog.constants import (
    TREND_FILTER_TYPE_EVENTS,
    RetentionQueryType,
)
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import property_to_expr, entity_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRangeWithIntervals
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.util import correct_result_for_sampling
from posthog.schema import (
    HogQLQueryModifiers,
    RetentionQueryResponse,
    IntervalType,
    RetentionEntity,
)
from posthog.schema import RetentionQuery, RetentionType

DEFAULT_INTERVAL = IntervalType("day")
DEFAULT_TOTAL_INTERVALS = 11


class RetentionQueryRunner(QueryRunner):
    query: RetentionQuery
    query_type = RetentionQuery

    def __init__(
        self,
        query: RetentionQuery | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

    def get_applicable_entity(self, event_query_type):
        default_entity = RetentionEntity(
            **{
                "id": "$pageview",
                "type": TREND_FILTER_TYPE_EVENTS,
            }
        )
        target_entity = self.query.retentionFilter.target_entity or default_entity
        if event_query_type in [RetentionQueryType.TARGET, RetentionQueryType.TARGET_FIRST_TIME]:
            return target_entity

        return self.query.retentionFilter.returning_entity or target_entity

    def retention_events_query(self, event_query_type) -> ast.SelectQuery:
        start_of_interval_sql = self.query_date_range.get_start_of_interval_hogql(
            source=ast.Field(chain=["events", "timestamp"])
        )

        if event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
            event_date_expr = ast.Call(name="min", args=[start_of_interval_sql])
        else:
            event_date_expr = start_of_interval_sql

        target_field = "person_id"
        if self.query.aggregation_group_type_index is not None:
            group_index = int(self.query.aggregation_group_type_index)
            if 0 <= group_index <= 4:
                target_field = f"$group_{group_index}"

        fields = [
            ast.Alias(alias="event_date", expr=event_date_expr),
            ast.Alias(alias="target", expr=ast.Field(chain=["events", target_field])),
        ]

        if event_query_type in [RetentionQueryType.TARGET, RetentionQueryType.TARGET_FIRST_TIME]:
            source_timestamp = ast.Field(chain=["events", "timestamp"])
            if event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
                source_timestamp = ast.Call(
                    name="min",
                    args=[source_timestamp],
                )

            datediff_call = ast.Call(
                name="dateDiff",
                args=[
                    ast.Constant(value=self.query_date_range.interval_name),
                    self.query_date_range.get_start_of_interval_hogql(),
                    self.query_date_range.get_start_of_interval_hogql(
                        source=source_timestamp,
                    ),
                ],
            )
            fields.append(
                ast.Alias(alias="breakdown_values", expr=ast.Array(exprs=[datediff_call])),
            )

        event_filters = [
            entity_to_expr(entity=self.get_applicable_entity(event_query_type)),
        ]

        if self.query.properties is not None and self.query.properties != []:
            event_filters.append(property_to_expr(self.query.properties, self.team))

        if (
            self.query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for prop in self.team.test_account_filters:
                event_filters.append(property_to_expr(prop, self.team))

        date_filter_expr = self.date_filter_expr(event_query_type)
        if event_query_type != RetentionQueryType.TARGET_FIRST_TIME:
            event_filters.append(date_filter_expr)

        group_by_fields = None
        having_expr = None
        if event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
            group_by_fields = [ast.Field(chain=["target"])]
            having_expr = date_filter_expr
        elif event_query_type == RetentionQueryType.RETURNING:
            group_by_fields = [ast.Field(chain=["target"]), ast.Field(chain=["event_date"])]

        result = ast.SelectQuery(
            select=fields,
            distinct=event_query_type == RetentionQueryType.TARGET,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=event_filters),
            group_by=group_by_fields,
            having=having_expr,
        )

        if self.query.samplingFactor is not None and isinstance(self.query.samplingFactor, float):
            result.select_from.sample = ast.SampleExpr(
                sample_value=ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor))
            )

        return result

    def date_filter_expr(self, event_query_type) -> ast.Expr:
        field_to_compare = (
            ast.Field(chain=["event_date"])
            if event_query_type == RetentionQueryType.TARGET_FIRST_TIME
            else ast.Field(chain=["events", "timestamp"])
        )
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=field_to_compare,
                    right=ast.Constant(value=self.query_date_range.date_from()),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=field_to_compare,
                    right=ast.Constant(value=self.query_date_range.date_to()),
                ),
            ]
        )

    def build_target_event_query(self) -> ast.SelectQuery:
        event_query_type = (
            RetentionQueryType.TARGET_FIRST_TIME
            if self.query.retentionFilter.retention_type == RetentionType.retention_first_time
            else RetentionQueryType.TARGET
        )
        return self.retention_events_query(event_query_type=event_query_type)

    def build_returning_event_query(self) -> ast.SelectQuery:
        return self.retention_events_query(event_query_type=RetentionQueryType.RETURNING)

    def actor_query(self) -> ast.SelectQuery:
        placeholders = {
            **self.query_date_range.to_placeholders(),
            "returning_event_query": self.build_returning_event_query(),
            "target_event_query": self.build_target_event_query(),
            "breakdown_values_filter": ast.Constant(value=None),
            "selected_interval": ast.Constant(value=None),
        }
        return parse_select(
            """
            SELECT DISTINCT breakdown_values,
                            intervals_from_base,
                            actor_id

            FROM (
                     SELECT target_event.breakdown_values AS breakdown_values,
                            dateDiff(
                                    {interval},
                                    target_event.event_date,
                                    returning_event.event_date
                            )                             AS intervals_from_base,
                            returning_event.target        AS actor_id

                     FROM {target_event_query} AS target_event
                              JOIN {returning_event_query} AS returning_event
                                   ON returning_event.target = target_event.target

                     WHERE returning_event.event_date > target_event.event_date

                     UNION ALL

                     SELECT target_event.breakdown_values AS breakdown_values,
                            0                             AS intervals_from_base,
                            target_event.target           AS actor_id

                     FROM {target_event_query} AS target_event
                     )

            WHERE ({breakdown_values_filter} is NULL OR breakdown_values = {breakdown_values_filter})
              AND ({selected_interval} is NULL OR intervals_from_base = {selected_interval})
            """,
            placeholders,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        placeholders = {
            "actor_query": self.actor_query(),
        }
        with self.timings.measure("retention_query"):
            retention_query = parse_select(
                """
                    SELECT actor_activity.breakdown_values         AS breakdown_values,
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
        total_intervals = self.query.retentionFilter.total_intervals or DEFAULT_TOTAL_INTERVALS
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

    def _is_stale(self, cached_result_package):
        date_to = self.query_date_range.date_to()
        interval = self.query_date_range.interval_name
        return is_stale(self.team, date_to, interval, cached_result_package)

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

    def calculate(self) -> RetentionQueryResponse:
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team.pk)

        response = execute_hogql_query(
            query_type="RetentionQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
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
                "date": (
                    self.query_date_range.date_from()
                    + self.query_date_range.determine_time_delta(
                        first_interval, self.query_date_range.interval_name.title()
                    )
                ),
            }
            for first_interval in range(self.query_date_range.total_intervals)
        ]

        return RetentionQueryResponse(results=results, timings=response.timings, hogql=hogql)
