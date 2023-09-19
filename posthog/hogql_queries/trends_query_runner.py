from typing import List, Optional, Any, Dict, Union

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models import Team
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
                                        toStartOfDay(toDateTime('2023-09-18 23:59:59')) - toIntervalDay(number) AS day_start
                                    FROM numbers(
                                            coalesce(dateDiff('day', toStartOfDay(toDateTime('2023-09-11 00:00:00')), toDateTime('2023-09-18 23:59:59')), 0)
                                        )
                                    UNION ALL
                                    SELECT
                                        0 AS total,
                                        toStartOfDay(toDateTime('2023-09-11 00:00:00'))
                                    UNION ALL
                                    SELECT
                                        count(*) AS total,
                                        toStartOfDay(toTimeZone(toDateTime(timestamp), 'UTC')) AS date
                                    FROM events AS e
                                    WHERE (team_id = 1) AND ({event}) AND (toTimeZone(timestamp, 'UTC') >= toStartOfDay(toDateTime('2023-09-11 00:00:00'))) AND (toTimeZone(timestamp, 'UTC') <= toDateTime('2023-09-18 23:59:59'))
                                    GROUP BY date
                                )
                                GROUP BY day_start
                                ORDER BY day_start ASC
                            )
                        """,
                        placeholders=self.series_placeholder(series),
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

    def series_placeholder(self, series: EventsNode | ActionsNode) -> Dict[str, Any]:
        if series.event is not None:
            return {"event": parse_expr("event = '{event}'".format(event=series.event))}

        return {"event": parse_expr("1 = 1")}
