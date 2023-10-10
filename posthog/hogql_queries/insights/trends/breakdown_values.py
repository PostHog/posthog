from typing import List
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team


class BreakdownValues:
    team: Team
    event_name: str
    breakdown_field: str
    query_date_range: QueryDateRange

    def __init__(self, team: Team, event_name: str, breakdown_field: str, query_date_range: QueryDateRange):
        self.team = team
        self.event_name = event_name
        self.breakdown_field = breakdown_field
        self.query_date_range = query_date_range

    def get_breakdown_values(self) -> List[str]:
        select_field = ast.Alias(alias="value", expr=ast.Field(chain=["properties", self.breakdown_field]))

        query = parse_select(
            """
                SELECT groupArray(value) FROM (
                    SELECT
                        {select_field},
                        count(*) as count
                    FROM
                        events e
                    WHERE
                        {events_where}
                    GROUP BY
                        value
                    ORDER BY
                        count DESC,
                        value DESC
                    LIMIT 25
                    OFFSET 0
                )
            """,
            placeholders={
                "events_where": self._where_filter(),
                "team_id": ast.Constant(value=self.team.pk),
                "select_field": select_field,
            },
        )

        response = execute_hogql_query(
            query_type="TrendsQueryBreakdownValues",
            query=query,
            team=self.team,
        )

        values = response.results[0][0]

        return values

    def _where_filter(self) -> ast.Expr:
        filters: List[ast.Expr] = []

        filters.append(parse_expr("team_id = {team_id}", placeholders={"team_id": ast.Constant(value=self.team.pk)}))
        filters.append(parse_expr("notEmpty(e.person_id)"))
        filters.extend(
            [
                parse_expr(
                    "toTimeZone(timestamp, 'UTC') >= {date_from}",
                    placeholders=self.query_date_range.to_placeholders(),
                ),
                parse_expr(
                    "toTimeZone(timestamp, 'UTC') <= {date_to}",
                    placeholders=self.query_date_range.to_placeholders(),
                ),
            ]
        )

        if self.event_name is not None:
            filters.append(parse_expr("event = {event}", placeholders={"event": ast.Constant(value=self.event_name)}))

        return ast.And(exprs=filters)
