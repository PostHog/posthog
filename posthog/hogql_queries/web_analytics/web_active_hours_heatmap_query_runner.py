from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import (
    WebAnalyticsQueryRunner,
)
from posthog.schema import (
    CachedWebActiveHoursHeatMapQueryResponse,
    WebActiveHoursHeatMapQuery,
    WebActiveHoursHeatMapQueryResponse,
    WebActiveHoursHeatMapDayAndHourResult,
    WebActiveHoursHeatMapDayResult,
    WebActiveHoursHeatMapHourResult,
    WebActiveHoursHeatMapStructuredResult,
)


class WebActiveHoursHeatMapQueryRunner(WebAnalyticsQueryRunner):
    query: WebActiveHoursHeatMapQuery
    response: WebActiveHoursHeatMapQueryResponse
    cached_response: CachedWebActiveHoursHeatMapQueryResponse

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
                    uniqMap(map(concat(toString(toDayOfWeek(timestamp)), ',' ,toString(toHour(timestamp))), events.person_id)) as hoursAndDays,
                    uniqMap(map(toHour(timestamp), events.person_id)) as hours,
                    uniqMap(map(toDayOfWeek(timestamp), events.person_id)) as days,
                    uniq(person_id) as total
                FROM events
                WHERE and(
                    event = '$pageview',
                    {all_properties},
                    {current_period}
                )
            ) as query
            """,
            placeholders={
                "all_properties": self._all_properties(),
                "current_period": self._current_period_expression(field="timestamp"),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def calculate(self):
        query = self.to_query()
        response = execute_hogql_query(
            query_type="date_and_time_heatmap_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        day_and_hours: list[WebActiveHoursHeatMapDayAndHourResult] = []
        days: list[WebActiveHoursHeatMapDayResult] = []
        hours: list[WebActiveHoursHeatMapHourResult] = []

        if not response.results:
            return WebActiveHoursHeatMapQueryResponse(
                results=WebActiveHoursHeatMapStructuredResult(
                    dayAndHours=day_and_hours, days=days, hours=hours, total=0
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
            day_and_hours.append(WebActiveHoursHeatMapDayAndHourResult(day=day, hour=hour, total=total))

        # Process day-only entries
        for i in range(len(days_keys)):
            day = int(days_keys[i])
            total = int(days_values[i])
            days.append(WebActiveHoursHeatMapDayResult(day=day, total=total))

        # Process hour-only entries
        for i in range(len(hours_keys)):
            hour = int(hours_keys[i])
            total = int(hours_values[i])
            hours.append(WebActiveHoursHeatMapHourResult(hour=hour, total=total))

        return WebActiveHoursHeatMapQueryResponse(
            results=WebActiveHoursHeatMapStructuredResult(
                dayAndHours=day_and_hours, days=days, hours=hours, total=totalOverall
            ),
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )

    def _all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)
