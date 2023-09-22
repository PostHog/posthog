from datetime import timedelta
from itertools import groupby
from math import ceil
from operator import itemgetter
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
from posthog.hogql_queries.utils.formula_ast import FormulaAST
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import ActionsNode, EventsNode, HogQLQueryResponse, TrendsQuery, TrendsQueryResponse


class SeriesWithExtras:
    series: EventsNode | ActionsNode
    is_previous_period_series: Optional[bool]

    def __init__(self, series: EventsNode | ActionsNode, is_previous_period_series: Optional[bool]):
        self.series = series
        self.is_previous_period_series = is_previous_period_series


class TrendsQueryRunner(QueryRunner):
    query: TrendsQuery
    query_type = TrendsQuery
    series: List[SeriesWithExtras]

    def __init__(self, query: TrendsQuery | Dict[str, Any], team: Team, timings: Optional[HogQLTimings] = None):
        super().__init__(query, team, timings)
        self.series = self.setup_series()

    def to_query(self) -> List[ast.SelectQuery]:
        queries = []
        with self.timings.measure("trends_query"):
            for series in self.series:
                if not series.is_previous_period_series:
                    date_placeholders = self.query_date_range.to_placeholders()
                else:
                    date_placeholders = self.query_previous_date_range.to_placeholders()

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
                                    FROM
                                        numbers(
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
                                    %s
                                    WHERE {events_filter}
                                    GROUP BY date
                                )
                                GROUP BY day_start
                                ORDER BY day_start ASC
                            )
                        """
                        % (self.sample_value()),
                        placeholders={
                            **date_placeholders,
                            "events_filter": self.events_filter(series),
                            "aggregation_operation": self.aggregation_operation(series.series),
                        },
                        timings=self.timings,
                    )
                )
        return queries

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

    def to_persons_query(self) -> str:
        # TODO: add support for selecting and filtering by breakdowns
        raise NotImplementedError()

    def calculate(self):
        queries = self.to_query()

        res = []
        timings = []

        for index, query in enumerate(queries):
            series_with_extra = self.series[index]

            response = execute_hogql_query(
                query_type="TrendsQuery",
                query=query,
                team=self.team,
                timings=self.timings,
            )

            timings.extend(response.timings)

            res.extend(self.build_series_response(response, series_with_extra))

        if self.query.trendsFilter is not None and self.query.trendsFilter.formula is not None:
            res = self.apply_formula(self.query.trendsFilter.formula, res)

        return TrendsQueryResponse(result=res, timings=timings)

    def build_series_response(self, response: HogQLQueryResponse, series: SeriesWithExtras):
        if response.results is None:
            return []

        res = []
        for val in response.results:
            series_object = {
                "data": val[1],
                "labels": [item.strftime("%-d-%b-%Y") for item in val[0]],  # Add back in hour formatting
                "days": [item.strftime("%Y-%m-%d") for item in val[0]],  # Add back in hour formatting
                "count": float(sum(val[1])),
                "label": "All events" if self.series_event(series.series) is None else self.series_event(series.series),
            }

            # Modifications for when comparing to previous period
            if self.query.trendsFilter is not None and self.query.trendsFilter.compare:
                labels = [
                    "{} {}".format(self.query.interval if self.query.interval is not None else "day", i)
                    for i in range(len(series_object["labels"]))
                ]

                series_object["compare"] = True
                series_object["compare_label"] = "previous" if series.is_previous_period_series else "current"
                series_object["labels"] = labels

            res.append(series_object)
        return res

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange, team=self.team, interval=self.query.interval, now=datetime.now()
        )

    @cached_property
    def query_previous_date_range(self):
        return QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange, team=self.team, interval=self.query.interval, now=datetime.now()
        )

    def aggregation_operation(self, series: EventsNode | ActionsNode) -> ast.Expr:
        if series.math == "hogql":
            return parse_expr(series.math_hogql)

        return parse_expr("count(*)")

    def events_filter(self, series_with_extra: SeriesWithExtras) -> ast.Expr:
        series = series_with_extra.series
        filters: List[ast.Expr] = []

        # Team ID
        filters.append(parse_expr("team_id = {team_id}", placeholders={"team_id": ast.Constant(value=self.team.pk)}))

        if not series_with_extra.is_previous_period_series:
            # Dates (current period)
            filters.extend(
                [
                    parse_expr(
                        "(toTimeZone(timestamp, 'UTC') >= {date_from})",
                        placeholders=self.query_date_range.to_placeholders(),
                    ),
                    parse_expr(
                        "(toTimeZone(timestamp, 'UTC') <= {date_to})",
                        placeholders=self.query_date_range.to_placeholders(),
                    ),
                ]
            )
        else:
            # Date (previous period)
            filters.extend(
                [
                    parse_expr(
                        "(toTimeZone(timestamp, 'UTC') >= {date_from})",
                        placeholders=self.query_previous_date_range.to_placeholders(),
                    ),
                    parse_expr(
                        "(toTimeZone(timestamp, 'UTC') <= {date_to})",
                        placeholders=self.query_previous_date_range.to_placeholders(),
                    ),
                ]
            )

        # Series
        if self.series_event(series) is not None:
            filters.append(
                parse_expr("event = {event}", placeholders={"event": ast.Constant(value=self.series_event(series))})
            )

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

        # Series Filters
        if series.properties is not None and series.properties != []:
            filters.append(property_to_expr(series.properties, self.team))

        if len(filters) == 0:
            return ast.Constant(value=True)
        elif len(filters) == 1:
            return filters[0]
        else:
            return ast.And(exprs=filters)

    # Using string interpolation for SAMPLE due to HogQL limitations with `UNION ALL` and `SAMPLE` AST nodes
    def sample_value(self) -> str:
        if self.query.samplingFactor is None:
            return ""

        return f"SAMPLE {self.query.samplingFactor}"

    def series_event(self, series: EventsNode | ActionsNode) -> str | None:
        if isinstance(series, EventsNode):
            return series.event
        return None

    def setup_series(self) -> List[SeriesWithExtras]:
        if self.query.trendsFilter is not None and self.query.trendsFilter.compare:
            updated_series = []
            for series in self.query.series:
                updated_series.append(SeriesWithExtras(series, is_previous_period_series=False))
                updated_series.append(SeriesWithExtras(series, is_previous_period_series=True))
            return updated_series

        return [SeriesWithExtras(series, is_previous_period_series=False) for series in self.query.series]

    def apply_formula(self, formula: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self.query.trendsFilter is not None and self.query.trendsFilter.compare:
            sorted_results = sorted(results, key=itemgetter("compare_label"))
            res = []
            for _, group in groupby(sorted_results, key=itemgetter("compare_label")):
                group_list = list(group)

                series_data = map(lambda s: s["data"], group_list)
                new_series_data = FormulaAST(series_data).call(formula)

                new_result = group_list[0]
                new_result["data"] = new_series_data
                new_result["count"] = float(sum(new_series_data))
                new_result["label"] = f"Formula ({formula})"

                res.append(new_result)
            return res

        series_data = map(lambda s: s["data"], results)
        new_series_data = FormulaAST(series_data).call(formula)
        new_result = results[0]

        new_result["data"] = new_series_data
        new_result["count"] = float(sum(new_series_data))
        new_result["label"] = f"Formula ({formula})"

        return [new_result]
