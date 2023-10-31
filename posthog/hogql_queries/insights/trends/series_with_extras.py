from typing import Optional
from posthog.schema import ActionsNode, EventsNode, TrendsQuery


class SeriesWithExtras:
    series: EventsNode | ActionsNode
    is_previous_period_series: Optional[bool]
    overriden_query: Optional[TrendsQuery]

    def __init__(
        self,
        series: EventsNode | ActionsNode,
        is_previous_period_series: Optional[bool],
        overriden_query: Optional[TrendsQuery],
    ):
        self.series = series
        self.is_previous_period_series = is_previous_period_series
        self.overriden_query = overriden_query
