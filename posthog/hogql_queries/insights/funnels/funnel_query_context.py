from typing import List, Optional, Union
from posthog.hogql.constants import LimitContext
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.query_context import QueryContext
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property.util import box_value
from posthog.models.team.team import Team
from posthog.schema import (
    BreakdownAttributionType,
    BreakdownFilter,
    BreakdownType,
    FunnelConversionWindowTimeUnit,
    FunnelsActorsQuery,
    FunnelsFilter,
    FunnelsQuery,
    HogQLQueryModifiers,
    IntervalType,
)


class FunnelQueryContext(QueryContext):
    query: FunnelsQuery
    funnelsFilter: FunnelsFilter
    breakdownFilter: BreakdownFilter

    interval: IntervalType

    breakdown: List[Union[str, int]] | None
    breakdownType: BreakdownType
    breakdownAttributionType: BreakdownAttributionType

    funnelWindowInterval: int
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit

    actorsQuery: FunnelsActorsQuery | None

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
        self.interval = self.query.interval or IntervalType.day

        self.breakdownType = self.breakdownFilter.breakdown_type or BreakdownType.event
        self.breakdownAttributionType = (
            self.funnelsFilter.breakdownAttributionType or BreakdownAttributionType.first_touch
        )
        self.funnelWindowInterval = self.funnelsFilter.funnelWindowInterval or 14
        self.funnelWindowIntervalUnit = (
            self.funnelsFilter.funnelWindowIntervalUnit or FunnelConversionWindowTimeUnit.day
        )

        # the API accepts either:
        #   a string (single breakdown) in parameter "breakdown"
        #   a list of numbers (one or more cohorts) in parameter "breakdown"
        #   a list of strings (multiple breakdown) in parameter "breakdowns"
        # if the breakdown is a string, box it as a list to reduce paths through the code
        #
        # The code below ensures that breakdown is always an array
        # without it affecting the multiple areas of the code outside of funnels that use breakdown
        #
        # Once multi property breakdown is implemented in Trends this becomes unnecessary

        # if isinstance(self.breakdownFilter.breakdowns, List) and self.breakdownType in [
        #     "person",
        #     "event",
        #     "hogql",
        #     None,
        # ]:
        #     self.breakdown = [
        #         b.property if isinstance(b.property, str) else int(b.property) for b in self.breakdownFilter.breakdowns
        #     ]

        if isinstance(self.breakdownFilter.breakdown, str) and self.breakdownType in [
            "person",
            "event",
            "hogql",
            None,
        ]:
            boxed_breakdown: List[Union[str, int]] = box_value(self.breakdownFilter.breakdown)
            self.breakdown = boxed_breakdown
        else:
            self.breakdown = self.breakdownFilter.breakdown  # type: ignore

    @cached_property
    def max_steps(self) -> int:
        return len(self.query.series)
