from typing import Optional
from posthog.hogql.constants import LimitContext
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.query_context import QueryContext
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team.team import Team
from posthog.schema import (
    BreakdownAttributionType,
    BreakdownFilter,
    FunnelConversionWindowTimeUnit,
    FunnelsFilter,
    FunnelsQuery,
    HogQLQueryModifiers,
)


class FunnelQueryContext(QueryContext):
    query: FunnelsQuery
    funnelsFilter: FunnelsFilter
    breakdownFilter: BreakdownFilter

    funnelWindowInterval: int
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit

    def __init__(
        self,
        query: FunnelsQuery,
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(query=query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

        self.funnelsFilter = self.query.funnelsFilter or FunnelsFilter()
        self.breakdownFilter = self.query.breakdownFilter or BreakdownFilter()

        # defaults
        self.breakdownAttributionType = (
            self.funnelsFilter.breakdownAttributionType or BreakdownAttributionType.first_touch
        )
        self.funnelWindowInterval = self.funnelsFilter.funnelWindowInterval or 14
        self.funnelWindowIntervalUnit = (
            self.funnelsFilter.funnelWindowIntervalUnit or FunnelConversionWindowTimeUnit.day
        )

    @cached_property
    def max_steps(self) -> int:
        return len(self.query.series)
