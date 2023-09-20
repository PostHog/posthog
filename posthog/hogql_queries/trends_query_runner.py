from datetime import timedelta
from math import ceil
from typing import List, Optional, Any, Dict

from django.utils.timezone import datetime
from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.caching.utils import is_stale

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
    query_type = TrendsQuery

    def __init__(self, query: TrendsQuery | Dict[str, Any], team: Team, timings: Optional[HogQLTimings] = None):
        super().__init__(query, team, timings)

    def to_query(self) -> List[ast.SelectQuery]:
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
                                        {aggregation_operation} AS total,
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
                            "aggregation_operation": self.aggregation_operation(series),
                        },
                        timings=self.timings,
                    )
                )
        return queries

    def to_persons_query(self) -> str:
        # TODO: add support for selecting and filtering by breakdowns
        raise NotImplementedError()

    def calculate(self):
        queries = self.to_query()

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

    def aggregation_operation(self, series: EventsNode | ActionsNode) -> ast.Expr:
        if series.math == "hogql":
            return parse_expr(series.math_hogql)

        return parse_expr("count(*)")

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
