from datetime import datetime, timedelta
from math import ceil
from typing import Any, Dict
from typing import Optional

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.caching.utils import is_stale
from posthog.constants import (
    PAGEVIEW_EVENT,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_LINEAR,
    RetentionQueryType,
)
from posthog.hogql import ast
from posthog.hogql.parser import parse_select, parse_expr
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRangeWithIntervals
from posthog.models import Team
from posthog.models.action.util import Action
from posthog.models.filters.mixins.retention import RetentionDateDerivedMixin
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.retention.types import CohortKey
from posthog.queries.util import correct_result_for_sampling
from posthog.schema import (
    HogQLQueryModifiers,
    RetentionQueryResponse,
    IntervalType,
    RetentionFilter,
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
        in_export_context: Optional[bool] = None,
        event_query_type: Optional[RetentionQueryType] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, in_export_context=in_export_context)
        self.event_query_type = event_query_type
        if not self.query.retentionFilter:
            self.query.retentionFilter = RetentionFilter()  # TODO: Clarify default filter

        self.target_entity = self.query.retentionFilter.target_entity or {
            "id": "$pageview",
            "type": TREND_FILTER_TYPE_EVENTS,
        }
        self.returning_entity = self.query.retentionFilter.returning_entity or self.target_entity

    def retention_events_query(self):
        _fields = [
            self.get_timestamp_field(),
            "events.person_id as target",
        ]
        params = {}

        if self.event_query_type in [RetentionQueryType.TARGET, RetentionQueryType.TARGET_FIRST_TIME]:
            source_timestamp = (
                "min(events.timestamp)"
                if self.event_query_type == RetentionQueryType.TARGET_FIRST_TIME
                else "events.timestamp"
            )

            _fields += [
                f"""
                [
                    dateDiff(
                        {{period}},
                        {self.query_date_range.get_start_of_interval_sql(source='{start_date}')},
                        {self.query_date_range.get_start_of_interval_sql(source=source_timestamp)}
                    )
                ] as breakdown_values
                """
            ]

        params.update(
            {
                "start_date": self.query_date_range.date_from(),
                "period": self.query_date_range.interval_name,
            }
        )

        date_query, date_params = self._get_date_filter()
        params.update(date_params)

        filter_expressions = []
        if self.query.properties is not None and self.query.properties != []:
            filter_expressions.append(property_to_expr(self.query.properties, self.team))

        filter_expressions.append(
            self.entity_to_expr(
                entity=self.target_entity
                if self.event_query_type == RetentionQueryType.TARGET
                or self.event_query_type == RetentionQueryType.TARGET_FIRST_TIME
                else self.returning_entity
            )
        )

        hogql_params = {key: ast.Constant(value=value) for key, value in params.items()}

        data_query_hogql = parse_expr(date_query, placeholders=hogql_params)
        if self.event_query_type != RetentionQueryType.TARGET_FIRST_TIME:
            filter_expressions.append(data_query_hogql)

        group_by_fields = None
        having_expr = None
        if self.event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
            group_by_fields = [ast.Field(chain=["target"])]
            having_expr = data_query_hogql
        if self.event_query_type == RetentionQueryType.RETURNING:
            group_by_fields = [ast.Field(chain=["target"]), ast.Field(chain=["event_date"])]

        query = f"SELECT {','.join(_fields)} FROM events"
        result = parse_select(
            query,
            placeholders={
                **hogql_params,
                "filter_where": ast.And(exprs=filter_expressions)
                if len(filter_expressions) > 1
                else filter_expressions[0],
            },
            timings=self.timings,
        )
        result.where = ast.And(exprs=filter_expressions)
        result.group_by = group_by_fields
        result.having = having_expr

        sampling_factor = self.query.samplingFactor
        if sampling_factor is not None and isinstance(sampling_factor, float):
            sample_expr = ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=sampling_factor)))
            result.select_from.sample = sample_expr

        return result

    def get_timestamp_field(self) -> str:
        start_of_interval_sql = self.query_date_range.get_start_of_interval_sql(
            source="events.timestamp",
        )
        if self.event_query_type == RetentionQueryType.TARGET:
            return f"DISTINCT {start_of_interval_sql} AS event_date"
        elif self.event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
            return f"min({start_of_interval_sql}) as event_date"
        else:
            return f"{start_of_interval_sql} AS event_date"

    def entity_to_expr(self, entity: dict) -> ast.Expr:
        if entity["type"] == TREND_FILTER_TYPE_ACTIONS and entity["id"] is not None:
            action = Action.objects.get(pk=entity["id"])
            return action_to_expr(action)
        elif entity["type"] == TREND_FILTER_TYPE_EVENTS:
            if entity["id"] is None:
                return ast.Constant(value=True)

            return ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["events", "event"]),
                right=ast.Constant(value=entity["id"]),
            )

        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["events", "event"]),
            right=ast.Constant(value=PAGEVIEW_EVENT),
        )

    def _get_date_filter(self):
        query = (
            f"event_date >= {{{self.event_query_type}_start_date}} AND event_date <= {{{self.event_query_type}_end_date}}"
            if self.event_query_type == RetentionQueryType.TARGET_FIRST_TIME
            else f"events.timestamp >= {{{self.event_query_type}_start_date}} AND events.timestamp <= {{{self.event_query_type}_end_date}}"
        )
        start_date = self.query_date_range.date_from()
        end_date = (
            (self.query_date_range.date_from() + self.query.retentionFilter.period_increment)
            if self.query.retentionFilter == TRENDS_LINEAR  # .display == linear TODO: ???
            and self.event_query_type == RetentionQueryType.TARGET
            else self.query_date_range.date_to()
        )
        if self.query_date_range._interval != IntervalType("hour"):
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
        params = {
            f"{self.event_query_type}_start_date": start_date,
            f"{self.event_query_type}_end_date": end_date,
        }
        return query, params

    def build_target_event_query(self):
        runner = RetentionQueryRunner(
            query=self.query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            in_export_context=self.in_export_context,
            event_query_type=(
                RetentionQueryType.TARGET_FIRST_TIME
                if self.query.retentionFilter.retention_type == RetentionType.retention_first_time
                else RetentionQueryType.TARGET
            ),
        )
        return runner.retention_events_query()

    def build_returning_event_query(self):
        runner = RetentionQueryRunner(
            query=self.query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            in_export_context=self.in_export_context,
            event_query_type=RetentionQueryType.RETURNING,
        )
        return runner.retention_events_query()

    # property_to_expr
    # null person filter -> ignore
    # format_action_filter -> action_to_expr
    # startofweek etc -> look into lifecycle query

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
    def query_date_range(self):
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
            CohortKey(tuple(breakdown_values), intervals_from_base): {
                "count": correct_result_for_sampling(count, self.query.samplingFactor),
                "people": [],
                "people_url": "",  # TODO: URL
            }
            for (breakdown_values, intervals_from_base, count) in response.results
        }

        results = [
            {
                "values": [
                    result_dict.get(CohortKey((first_day,), day), {"count": 0, "people": [], "people_url": ""})
                    for day in range(self.query_date_range.total_intervals - first_day)
                ],
                "label": f"{self.query_date_range.interval_name.title()} {first_day}",
                "date": self.query_date_range.date_from()
                + RetentionDateDerivedMixin.determine_time_delta(
                    first_day, self.query_date_range.interval_name.title()
                )[0],  # TODO: fix
                "people_url": "",  # TODO: URL
            }
            for first_day in range(self.query_date_range.total_intervals)
        ]

        return RetentionQueryResponse(results=results, timings=response.timings, hogql=hogql)
