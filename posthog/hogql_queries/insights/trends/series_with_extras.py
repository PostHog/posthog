from typing import Optional, Union

from posthog.schema import ActionsNode, DataWarehouseNode, EventsNode, TrendsQuery


class SeriesWithExtras:
    series: Union[EventsNode, ActionsNode, DataWarehouseNode]
    series_order: int
    is_previous_period_series: Optional[bool]
    overriden_query: Optional[TrendsQuery]
    aggregate_values: Optional[bool]

    def __init__(
        self,
        series: Union[EventsNode, ActionsNode, DataWarehouseNode],
        series_order: int,
        is_previous_period_series: Optional[bool],
        overriden_query: Optional[TrendsQuery],
        aggregate_values: Optional[bool],
    ):
        self.series = series
        self.series_order = series_order
        self.is_previous_period_series = is_previous_period_series
        self.overriden_query = overriden_query
        self.aggregate_values = aggregate_values
