from datetime import timedelta
from math import ceil
from typing import List, Optional, Any, Dict, cast

from django.utils.timezone import datetime
from posthog.caching.insights_api import (
    BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL,
)
from posthog.caching.utils import is_stale

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.models.action.action import Action
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    ActionsNode,
    EventsNode,
    StickinessQuery,
    HogQLQueryModifiers,
    StickinessQueryResponse,
)


class StickinessQueryRunner(QueryRunner):
    query: StickinessQuery
    query_type = StickinessQuery

    def __init__(
        self,
        query: StickinessQuery | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

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

    def to_query(self) -> ast.SelectQuery:
        select_query = parse_select(
            """
                SELECT groupArray(aggregation_target), groupArray(num_intervals)
                FROM (
                    SELECT count(DISTINCT aggregation_target) as aggregation_target, num_intervals
                    FROM (
                        SELECT e.person_id as aggregation_target, count(DISTINCT toStartOfDay(e.timestamp)) as num_intervals
                        FROM events e
                        WHERE {where_clause}
                        GROUP BY aggregation_target
                    )
                    WHERE num_intervals <= {num_intervals}
                    GROUP BY num_intervals
                    ORDER BY num_intervals
                )
            """,
            placeholders={
                "where_clause": self.where_clause(),
                "num_intervals": ast.Constant(value=self.intervals_num()),
            },
        )

        return cast(ast.SelectQuery, select_query)

    def to_actors_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        return ast.SelectUnionQuery(select_queries=[])

    def calculate(self):
        queries = self.to_query()

        response = execute_hogql_query(
            query_type="StickinessQuery",
            query=queries,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        res = []
        timings = []

        for val in response.results or []:
            try:
                # TODO: Split out series[]
                series_label = self.series_event(self.query.series[0])
            except Action.DoesNotExist:
                # Dont append the series if the action doesnt exist
                continue

            data = val[0]

            series_object = {
                "count": sum(data),
                "data": data,
                "days": val[1],
                "label": "All events" if series_label is None else series_label,
                "labels": [f"{day} day{'s' if day == 1 else ''}" for day in val[1]],
            }

            res.append(series_object)

        return StickinessQueryResponse(results=res, timings=timings)

    def where_clause(self) -> ast.Expr:
        filters: List[ast.Expr] = []

        filters.extend(
            [
                parse_expr(
                    "timestamp >= {date_from_with_adjusted_start_of_interval}",
                    placeholders=self.query_date_range.to_placeholders(),
                ),
                parse_expr(
                    "timestamp <= {date_to}",
                    placeholders=self.query_date_range.to_placeholders(),
                ),
            ]
        )

        # TODO: Split out series[]
        # Series
        filters.append(
            parse_expr(
                "event = {event}",
                placeholders={"event": ast.Constant(value=self.query.series[0].name)},
            )
        )

        # Filter Test Accounts
        if (
            self.query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for property in self.team.test_account_filters:
                filters.append(property_to_expr(property, self.team))

        if len(filters) == 0:
            return ast.Constant(value=True)
        elif len(filters) == 1:
            return filters[0]
        else:
            return ast.And(exprs=filters)

    def series_event(self, series: EventsNode | ActionsNode) -> str | None:
        if isinstance(series, EventsNode):
            return series.event
        if isinstance(series, ActionsNode):
            # TODO: Can we load the Action in more efficiently?
            action = Action.objects.get(pk=int(series.id), team=self.team)
            return action.name
        return None

    def intervals_num(self):
        delta = self.query_date_range.date_to() - self.query_date_range.date_from()
        return delta.days + 2

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=datetime.now(),
        )
