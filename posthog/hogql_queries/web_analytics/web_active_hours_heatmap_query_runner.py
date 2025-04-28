from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from typing import Optional
from posthog.schema import (
    CachedEventsHeatMapQueryResponse,
    EventsHeatMapQueryResponse,
    EventsHeatMapDataResult,
    EventsHeatMapRowAggregationResult,
    EventsHeatMapColumnAggregationResult,
    EventsHeatMapStructuredResult,
    EventsHeatMapQuery,
)


class EventsHeatMapQueryRunner(WebAnalyticsQueryRunner):
    query: EventsHeatMapQuery
    response: EventsHeatMapQueryResponse
    cached_response: CachedEventsHeatMapQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def to_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
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
                    uniqMap(map(concat(toString(toDayOfWeek(uniqueSessionEvents.timestamp)), ',' ,toString(toHour(uniqueSessionEvents.timestamp))), uniqueSessionEvents.person_id)) as hoursAndDays,
                    uniqMap(map(toHour(uniqueSessionEvents.timestamp), uniqueSessionEvents.person_id)) as hours,
                    uniqMap(map(toDayOfWeek(uniqueSessionEvents.timestamp), uniqueSessionEvents.person_id)) as days,
                    uniq(person_id) as total
                FROM (
                    SELECT
                        any(events.person_id) as person_id,
                        session.session_id as session_id,
                        min(session.$start_timestamp) as timestamp
                    FROM events
                    WHERE and(
                        {event_expr},
                        {all_properties}
                    )
                    GROUP BY session_id
                ) as uniqueSessionEvents
                WHERE {current_period}
            ) as query
            """,
            placeholders={
                "all_properties": self._all_properties(),
                "current_period": self._current_period_expression(field="timestamp"),
                "event_expr": self.getEventExpr(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def getEventExpr(self):
        if self.conversion_goal_expr:
            return self.conversion_goal_expr
        return self.getEvent()

    def getEvent(self) -> Optional[ast.Expr]:
        if self.query.source.event:
            return ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["events", "event"]),
                right=ast.Constant(value=self.query.source.event),
            )
        else:
            return ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["events", "event"]),
                right=ast.Constant(value="$pageview"),
            )

    def calculate(self):
        query = self.to_query()
        response = execute_hogql_query(
            query_type="web_active_hours_heatmap_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        day_and_hours: list[EventsHeatMapDataResult] = []
        days: list[EventsHeatMapRowAggregationResult] = []
        hours: list[EventsHeatMapColumnAggregationResult] = []

        if not response.results:
            return EventsHeatMapQueryResponse(
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
            day, hour = map(int, key.split(","))
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

        return EventsHeatMapQueryResponse(
            results=EventsHeatMapStructuredResult(
                data=day_and_hours, rowAggregations=days, columnAggregations=hours, allAggregations=totalOverall
            ),
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )

    def _all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)
