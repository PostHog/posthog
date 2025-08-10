from datetime import timedelta, datetime
from math import ceil
from typing import Any, Optional, Union

from django.db import models
from django.db.models.functions import Coalesce

from posthog.caching.insights_api import (
    BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REAL_TIME_INSIGHT_REFRESH_INTERVAL,
    REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL,
)
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.series_with_extras import SeriesWithExtras
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.models.action.action import Action
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property_definition import PropertyDefinition
from posthog.schema import (
    ActionConversionGoal,
    ActionsNode,
    CachedCalendarHeatmapQueryResponse,
    CustomEventConversionGoal,
    DashboardFilter,
    DataWarehouseNode,
    EventsNode,
    HogQLQueryModifiers,
    IntervalType,
    CalendarHeatmapQuery,
    CalendarHeatmapResponse,
    EventsHeatMapDataResult,
    EventsHeatMapRowAggregationResult,
    EventsHeatMapColumnAggregationResult,
    EventsHeatMapStructuredResult,
)

SEPARATOR = "','"

# We need to use a CTE, otherwise we'll get this error because of the sub-query containing some auto-generated conditions:
# Aggregate function any(if(NOT empty(events__override.distinct_id), events__override.person_id, events.person_id)) AS person_id is found in WHERE in query.
templateUniqueUsers = """
WITH uniqueSessionEvents AS (
    SELECT
        person_id,
        $session_id,
        timestamp
    FROM events
    WHERE and(
        {event_expr},
        {all_properties},
        {test_account_filters}
    )
),
uniqueSessionEventsGrouped AS (
    SELECT
        any(person_id) as person_id,
        $session_id as session_id,
        min(timestamp) as timestamp
    FROM uniqueSessionEvents
    GROUP BY $session_id
),
query AS (
    SELECT
        uniqMap(map(concatWithSeparator({separator},toString(toDayOfWeek(uniqueSessionEventsGrouped.timestamp)),toString(toHour(uniqueSessionEventsGrouped.timestamp))), uniqueSessionEventsGrouped.person_id)) as hoursAndDays,
        uniqMap(map(toHour(uniqueSessionEventsGrouped.timestamp), uniqueSessionEventsGrouped.person_id)) as hours,
        uniqMap(map(toDayOfWeek(uniqueSessionEventsGrouped.timestamp), uniqueSessionEventsGrouped.person_id)) as days,
        uniq(person_id) as total
    FROM uniqueSessionEventsGrouped
    WHERE {current_period}
)
SELECT
    mapKeys(query.hoursAndDays) as hoursAndDaysKeys,
    mapValues(query.hoursAndDays) as hoursAndDaysValues,
    mapKeys(query.hours) as hoursKeys,
    mapValues(query.hours) as hoursValues,
    mapKeys(query.days) as daysKeys,
    mapValues(query.days) as daysValues,
    query.total
FROM query
"""

templateAllUsers = """
SELECT
    mapKeys(query.hoursAndDays) as hoursAndDaysKeys,
    mapValues(query.hoursAndDays) as hoursAndDaysValues,
    mapKeys(query.hours) as hoursKeys,
    mapValues(query.hours) as hoursValues,
    mapKeys(query.days) as daysKeys,
    mapValues(query.days) as daysValues,
    query.total
FROM (
    SELECT
        sumMap(map(concatWithSeparator({separator},toString(toDayOfWeek(events.timestamp)) ,toString(toHour(events.timestamp))), 1)) as hoursAndDays,
        sumMap(map(toHour(events.timestamp), 1)) as hours,
        sumMap(map(toDayOfWeek(events.timestamp), 1)) as days,
        count(*) as total
    FROM events
    WHERE and(
        {event_expr},
        {all_properties},
        {test_account_filters},
        {current_period}
    )
) as query
"""


class CalendarHeatmapQueryRunner(QueryRunner):
    query: CalendarHeatmapQuery
    response: CalendarHeatmapResponse
    cached_response: CachedCalendarHeatmapQueryResponse
    series: list[SeriesWithExtras]

    def __init__(
        self,
        query: CalendarHeatmapQuery | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        if isinstance(query, dict):
            query = CalendarHeatmapQuery.model_validate(query)

        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

    def _refresh_frequency(self):
        date_to = self.query_date_range.date_to()
        date_from = self.query_date_range.date_from()
        interval = self.query_date_range.interval_name

        delta_days: Optional[int] = None
        if date_from and date_to:
            delta = date_to - date_from
            delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

        if interval == "minute":
            return REAL_TIME_INSIGHT_REFRESH_INTERVAL

        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            # The interval is shorter for short-term insights
            return REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL

    def to_query(self) -> ast.SelectQuery:
        # Use the heatmap query logic
        template = templateUniqueUsers if self.query.series[0].math == "dau" else templateAllUsers
        query = parse_select(
            template,
            placeholders={
                "all_properties": self._all_properties(),
                "test_account_filters": self._test_account_filters,
                "current_period": self._current_period_expression(field="timestamp"),
                "event_expr": self.getEventExpr(),
                "separator": ast.Constant(value=SEPARATOR),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def calculate(self):
        query = self.to_query()
        response = execute_hogql_query(
            query_type="calendar_heatmap_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        day_and_hours: list[EventsHeatMapDataResult] = []
        days: list[EventsHeatMapRowAggregationResult] = []
        hours: list[EventsHeatMapColumnAggregationResult] = []

        if not response.results:
            return CalendarHeatmapResponse(
                results=EventsHeatMapStructuredResult(
                    data=day_and_hours, rowAggregations=days, columnAggregations=hours, allAggregations=0
                ),
                timings=response.timings,
                hogql=response.hogql,
                modifiers=self.modifiers,
            )

        row = response.results[0]
        hours_and_days_keys = row[0]
        hours_and_days_values = row[1]
        hours_keys = row[2]
        hours_values = row[3]
        days_keys = row[4]
        days_values = row[5]
        totalOverall = row[6]
        # Process day-hour combinations
        for i in range(len(hours_and_days_keys)):
            key = hours_and_days_keys[i]
            day, hour = map(int, key.split(SEPARATOR))
            total = int(hours_and_days_values[i])
            day_and_hours.append(EventsHeatMapDataResult(row=day, column=hour, value=total))

        # Process day-only entries
        for i in range(len(days_keys)):
            day = int(days_keys[i])
            total = int(days_values[i])
            days.append(EventsHeatMapRowAggregationResult(row=day, value=total))

        # Process hour-only entries
        for i in range(len(hours_keys)):
            hour = int(hours_keys[i])
            total = int(hours_values[i])
            hours.append(EventsHeatMapColumnAggregationResult(column=hour, value=total))

        return CalendarHeatmapResponse(
            results=EventsHeatMapStructuredResult(
                data=day_and_hours, rowAggregations=days, columnAggregations=hours, allAggregations=totalOverall
            ),
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )

    @cached_property
    def _test_account_filters(self) -> ast.Expr:
        if not self.query.filterTestAccounts:
            return ast.Constant(value=True)
        if isinstance(self.team.test_account_filters, list) and len(self.team.test_account_filters) > 0:
            return property_to_expr(self.team.test_account_filters, team=self.team)
        else:
            return ast.Constant(value=True)

    def _all_properties(self) -> ast.Expr:
        # Collect all property expressions
        property_exprs = []

        # Add top-level properties if they exist
        if self.query.properties is not None and self.query.properties != []:
            property_exprs.append(property_to_expr(self.query.properties, team=self.team))

        # Add series-level properties if they exist (from the first series)
        if self.query.series and len(self.query.series) > 0:
            series = self.query.series[0]
            if hasattr(series, "properties") and series.properties is not None and series.properties != []:
                property_exprs.append(property_to_expr(series.properties, team=self.team))

        if len(property_exprs) == 0:
            return ast.Constant(value=True)
        elif len(property_exprs) == 1:
            return property_exprs[0]
        else:
            return ast.Call(name="and", args=property_exprs)

    def _current_period_expression(self, field="start_timestamp"):
        return ast.Call(
            name="and",
            args=[
                ast.CompareOperation(
                    left=ast.Field(chain=[field]),
                    right=self.query_date_range.date_from_as_hogql(),
                    op=ast.CompareOperationOp.GtEq,
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=[field]),
                    right=self.query_date_range.date_to_as_hogql(),
                    op=ast.CompareOperationOp.LtEq,
                ),
            ],
        )

    def getEventExpr(self):
        if self.conversion_goal_expr:
            return self.conversion_goal_expr
        return self.getEvent()

    @cached_property
    def conversion_goal_expr(self) -> Optional[ast.Expr]:
        if self.query.series[0].kind == "ActionsNode":
            action = Action.objects.get(pk=self.query.series[0].id, team__project_id=self.team.project_id)
            return action_to_expr(action)
        elif isinstance(self.query.conversionGoal, CustomEventConversionGoal):
            return ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                # Support for insights with actions
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=self.query.conversionGoal.customEventName),
            )

        # Support for web analytics
        if isinstance(self.query.conversionGoal, ActionConversionGoal):
            action = Action.objects.get(pk=self.query.conversionGoal.actionId, team__project_id=self.team.project_id)
            return action_to_expr(action)
        else:
            return None

    def getEvent(self) -> Optional[ast.Expr]:
        # Use event from the first series if available
        if (
            hasattr(self.query, "series")
            and self.query.series
            and hasattr(self.query.series[0], "event")
            and self.query.series[0].event
        ):
            return ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["events", "event"]),
                right=ast.Constant(value=self.query.series[0].event),
            )
        return ast.Constant(value=True)

    @cached_property
    def query_date_range(self):
        interval = IntervalType.DAY
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=interval,
            now=datetime.now(),
        )

    def series_event(self, series: Union[EventsNode, ActionsNode, DataWarehouseNode]) -> str | None:
        if isinstance(series, EventsNode):
            return series.event
        if isinstance(series, ActionsNode):
            # TODO: Can we load the Action in more efficiently?
            action = Action.objects.get(pk=int(series.id), team__project_id=self.team.project_id)
            return action.name

        if isinstance(series, DataWarehouseNode):
            return series.table_name

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        super().apply_dashboard_filters(dashboard_filter=dashboard_filter)

    def _event_property(
        self,
        field: str,
        field_type: PropertyDefinition.Type,
        group_type_index: Optional[int],
    ) -> str:
        try:
            return (
                PropertyDefinition.objects.alias(
                    effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
                )
                .get(
                    effective_project_id=self.team.project_id,  # type: ignore
                    name=field,
                    type=field_type,
                    group_type_index=group_type_index if field_type == PropertyDefinition.Type.GROUP else None,
                )
                .property_type
                or "String"
            )
        except PropertyDefinition.DoesNotExist:
            return "String"
