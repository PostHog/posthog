from typing import List, Optional, Any, Dict, Union

from django.utils.timezone import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import ActionsNode, EventsNode, TrendsQuery, TrendsQueryResponse


class TrendsQueryRunner(QueryRunner):
    query: TrendsQuery

    def __init__(self, query: TrendsQuery | Dict[str, Any], team: Team, timings: Optional[HogQLTimings] = None):
        super().__init__(team, timings)
        if isinstance(query, TrendsQuery):
            self.query = query
        else:
            self.query = TrendsQuery.parse_obj(query)

    def to_query(self) -> Union[List[ast.SelectQuery], ast.SelectQuery]:
        queries = []
        with self.timings.measure("trends_query"):
            for series in self.query.series:
                queries.append(
                    parse_select(
                        """
                            SELECT
                                groupArray(day_start) AS date,
                                groupArray(count) AS total
                            FROM
                            (
                                SELECT
                                    sum(total) AS count,
                                    day_start
                                FROM
                                (
                                    SELECT
                                        0 AS total,
                                        dateTrunc({interval}, {date_to}) - {number_interval_period} AS day_start
                                    FROM numbers(
                                            coalesce(dateDiff({interval}, {date_from}, {date_to}), 0)
                                        )
                                    UNION ALL
                                    SELECT
                                        0 AS total,
                                        {date_from}
                                    UNION ALL
                                    SELECT
                                        count(*) AS total,
                                        dateTrunc({interval}, toTimeZone(toDateTime(timestamp), 'UTC')) AS date
                                    FROM events AS e
                                    WHERE {events_filter}
                                    GROUP BY date
                                )
                                GROUP BY day_start
                                ORDER BY day_start ASC
                            )
                        """,
                        placeholders={
                            **self.query_date_range.to_placeholders(),
                            "events_filter": self.events_filter(series),
                        },
                        timings=self.timings,
                    )
                )
        return queries

    def to_persons_query(self) -> str:
        # TODO: add support for selecting and filtering by breakdowns
        raise NotImplementedError()

    def run(self) -> TrendsQueryResponse:
        to_query = self.to_query()
        queries = to_query if isinstance(to_query, list) else [to_query]

        res = []
        timings = []

        for index, query in enumerate(queries):
            series = self.query.series[index]

            response = execute_hogql_query(
                query_type="TrendsQuery",
                query=query,
                team=self.team,
                timings=self.timings,
            )

            timings.extend(response.timings)

            for val in response.results:
                res.append(
                    {
                        "data": val[1],
                        "labels": [item.strftime("%-d-%b-%Y") for item in val[0]],  # Add back in hour formatting
                        "days": [item.strftime("%Y-%m-%d") for item in val[0]],  # Add back in hour formatting
                        "count": float(sum(val[1])),
                        "label": "All events" if series.event is None else series.event,
                    }
                )

        return TrendsQueryResponse(result=res, timings=timings)

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange, team=self.team, interval=self.query.interval, now=datetime.now()
        )

    def events_filter(self, series: EventsNode | ActionsNode) -> ast.Expr:
        filters: List[ast.Expr] = []

        # Team ID
        filters.append(parse_expr("team_id = {team_id}", placeholders={"team_id": ast.Constant(value=self.team.pk)}))

        # Date From
        filters.append(
            parse_expr(
                "(toTimeZone(timestamp, 'UTC') >= {date_from})", placeholders=self.query_date_range.to_placeholders()
            )
        )

        # Date To
        filters.append(
            parse_expr(
                "(toTimeZone(timestamp, 'UTC') <= {date_to})", placeholders=self.query_date_range.to_placeholders()
            )
        )

        # Series
        if series.event is not None:
            filters.append(parse_expr("event = {event}", placeholders={"event": ast.Constant(value=series.event)}))

        # Filter Test Accounts
        if (
            self.query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for property in self.team.test_account_filters:
                filters.append(property_to_expr(property, self.team))

        # Properties
        if self.query.properties is not None and self.query.properties != []:
            filters.append(property_to_expr(self.query.properties, self.team))

        if len(filters) == 0:
            return ast.Constant(value=True)
        elif len(filters) == 1:
            return filters[0]
        else:
            return ast.And(exprs=filters)
