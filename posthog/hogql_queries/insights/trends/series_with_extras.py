from typing import Union

from posthog.schema import ActionsNode, DataWarehouseNode, EventsNode, TrendsQuery


class SeriesWithExtras:
    series: Union[EventsNode, ActionsNode, DataWarehouseNode]
    series_order: int
    is_previous_period_series: bool | None
    overriden_query: TrendsQuery | None
    aggregate_values: bool | None

    def __init__(
        self,
        series: Union[EventsNode, ActionsNode, DataWarehouseNode],
        series_order: int,
        is_previous_period_series: bool | None,
        overriden_query: TrendsQuery | None,
        aggregate_values: bool | None,
    ):
        self.series = series
        self.series_order = series_order
        self.is_previous_period_series = is_previous_period_series
        self.overriden_query = overriden_query
        self.aggregate_values = aggregate_values
