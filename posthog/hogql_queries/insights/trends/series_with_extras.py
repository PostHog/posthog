from typing import Optional
from posthog.schema import ActionsNode, EventsNode


class SeriesWithExtras:
    series: EventsNode | ActionsNode
    is_previous_period_series: Optional[bool]

    def __init__(self, series: EventsNode | ActionsNode, is_previous_period_series: Optional[bool]):
        self.series = series
        self.is_previous_period_series = is_previous_period_series
