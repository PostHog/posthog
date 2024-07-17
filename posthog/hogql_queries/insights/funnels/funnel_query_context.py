from typing import Optional, Union
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
    funnels_filter: FunnelsFilter
    breakdown_filter: BreakdownFilter

    interval: IntervalType

    breakdown: list[Union[str, int]] | str | int | None
    breakdownType: BreakdownType
    breakdown_attribution_type: BreakdownAttributionType

    funnel_window_interval: int
    funnel_window_interval_unit: FunnelConversionWindowTimeUnit

    actorsQuery: FunnelsActorsQuery | None

    includeTimestamp: Optional[bool]
    includePrecedingTimestamp: Optional[bool]
    includeProperties: list[str]
    includeFinalMatchingEvents: Optional[bool]

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

        self.funnels_filter = self.query.funnels_filter or FunnelsFilter()
        self.breakdown_filter = self.query.breakdown_filter or BreakdownFilter()

        # defaults
        self.interval = self.query.interval or IntervalType.DAY

        self.breakdownType = self.breakdown_filter.breakdown_type or BreakdownType.EVENT
        self.breakdown_attribution_type = (
            self.funnels_filter.breakdown_attribution_type or BreakdownAttributionType.FIRST_TOUCH
        )
        self.funnel_window_interval = self.funnels_filter.funnel_window_interval or 14
        self.funnel_window_interval_unit = (
            self.funnels_filter.funnel_window_interval_unit or FunnelConversionWindowTimeUnit.DAY
        )

        self.includeTimestamp = include_timestamp
        self.includePrecedingTimestamp = include_preceding_timestamp
        self.includeProperties = include_properties or []
        self.includeFinalMatchingEvents = include_final_matching_events

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

        if isinstance(self.breakdown_filter.breakdown, str) and self.breakdownType in [
            "person",
            "event",
            "hogql",
            None,
        ]:
            boxed_breakdown: list[Union[str, int]] = box_value(self.breakdown_filter.breakdown)
            self.breakdown = boxed_breakdown
        else:
            self.breakdown = self.breakdown_filter.breakdown

        self.actorsQuery = None

    @cached_property
    def max_steps(self) -> int:
        return len(self.query.series)
