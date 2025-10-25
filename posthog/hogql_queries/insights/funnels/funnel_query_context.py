from typing import Optional, Union

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

from posthog.hogql.constants import LimitContext
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.insights.query_context import QueryContext
from posthog.models.property.util import box_value
from posthog.models.team.team import Team


class FunnelQueryContext(QueryContext):
    query: FunnelsQuery
    actorsQuery: FunnelsActorsQuery | None

    includeTimestamp: Optional[bool]
    includePrecedingTimestamp: Optional[bool]
    includeProperties: list[str]
    includeFinalMatchingEvents: Optional[bool]

    max_steps_override: int | None = None

    def __init__(
        self,
        query: FunnelsQuery,
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
        include_timestamp: Optional[bool] = None,
        include_preceding_timestamp: Optional[bool] = None,
        include_properties: Optional[list[str]] = None,
        include_final_matching_events: Optional[bool] = None,
    ):
        super().__init__(query=query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

        self.includeTimestamp = include_timestamp
        self.includePrecedingTimestamp = include_preceding_timestamp
        self.includeProperties = include_properties or []
        self.includeFinalMatchingEvents = include_final_matching_events

        self.actorsQuery = None

    @property
    def breakdownFilter(self) -> BreakdownFilter:
        return self.query.breakdownFilter or BreakdownFilter()

    @property
    def breakdown(self) -> Optional[Union[list[Union[str, int]], str, int]]:
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

        # if isinstance(self._filter.breakdowns, List) and self._filter.breakdown_type in [
        #     "person",
        #     "event",
        #     "hogql",
        #     None,
        # ]:
        #     data.update({"breakdown": [b.get("property") for b in self._filter.breakdowns]})

        if isinstance(self.breakdownFilter.breakdown, str) and self.breakdownType in [
            "person",
            "event",
            "event_metadata",
            "hogql",
            None,
        ]:
            boxed_breakdown: list[Union[str, int]] = box_value(self.breakdownFilter.breakdown)
            return boxed_breakdown
        else:
            return self.breakdownFilter.breakdown

    @property
    def breakdownType(self) -> BreakdownType:
        return self.breakdownFilter.breakdown_type or BreakdownType.EVENT

    @property
    def funnelsFilter(self) -> FunnelsFilter:
        return self.query.funnelsFilter or FunnelsFilter()

    @property
    def breakdownAttributionType(self) -> BreakdownAttributionType:
        return self.funnelsFilter.breakdownAttributionType or BreakdownAttributionType.FIRST_TOUCH

    @property
    def interval(self) -> IntervalType:
        return self.query.interval or IntervalType.DAY

    @property
    def funnelWindowInterval(self) -> int:
        return self.funnelsFilter.funnelWindowInterval or 14

    @property
    def funnelWindowIntervalUnit(self) -> FunnelConversionWindowTimeUnit:
        return self.funnelsFilter.funnelWindowIntervalUnit or FunnelConversionWindowTimeUnit.DAY

    @property
    def max_steps(self) -> int:
        if self.max_steps_override is not None:
            return self.max_steps_override
        return len(self.query.series)
