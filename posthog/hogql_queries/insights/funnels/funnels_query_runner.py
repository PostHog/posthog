from datetime import timedelta
from math import ceil
from typing import List, Optional, Any, Dict, cast

from posthog.caching.insights_api import (
    BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL,
)
from posthog.caching.utils import is_stale
from posthog.constants import FunnelOrderType, FunnelVizType

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.funnels.funnel import Funnel
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models import Team
from posthog.schema import (
    FunnelsQuery,
    FunnelsQueryResponse,
    HogQLQueryModifiers,
)


class FunnelsQueryRunner(QueryRunner):
    query: FunnelsQuery
    query_type = FunnelsQuery
    context: FunnelQueryContext

    def __init__(
        self,
        query: FunnelsQuery | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

        self.context = FunnelQueryContext(
            query=self.query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context
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

    def to_query(self) -> ast.SelectQuery:
        funnelVizType, funnelOrderType = (
            self.context.funnelsFilter.funnelVizType,
            self.context.funnelsFilter.funnelOrderType,
        )

        dummy_query = cast(ast.SelectQuery, parse_select("SELECT 1"))  # placeholder for unimplemented funnel queries

        if funnelVizType == FunnelVizType.TRENDS:
            return dummy_query
        elif funnelVizType == FunnelVizType.TIME_TO_CONVERT:
            return dummy_query
        else:
            if funnelOrderType == FunnelOrderType.ORDERED:
                return dummy_query
            elif funnelOrderType == FunnelOrderType.STRICT:
                return dummy_query
            else:
                return Funnel(context=self.context).get_query()

    def calculate(self):
        query = self.to_query()

        res: List[Dict[str, Any]] = []
        timings = []

        response = execute_hogql_query(
            query_type="FunnelsQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        if response.timings is not None:
            timings.extend(response.timings)

        return FunnelsQueryResponse(results=res, timings=timings)
