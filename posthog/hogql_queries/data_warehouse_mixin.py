from posthog.schema import (
    ActionsNode,
    DataWarehouseEventsModifier,
    DataWarehouseNode,
    EventsNode,
    GroupNode,
    HogQLQueryModifiers,
)

from posthog.hogql import ast

from posthog.models.filters.mixins.utils import cached_property


class DataWarehouseInsightQueryMixin:
    series: EventsNode | ActionsNode | DataWarehouseNode | GroupNode

    @cached_property
    def _table_expr(self) -> ast.Field:
        if isinstance(self.series, DataWarehouseNode):
            return ast.Field(chain=[self.series.table_name])

        return ast.Field(chain=["events"])


def data_warehouse_events_modifier(series: DataWarehouseNode) -> DataWarehouseEventsModifier:
    return DataWarehouseEventsModifier(
        table_name=series.table_name,
        timestamp_field=series.timestamp_field,
        id_field=series.id_field,
        distinct_id_field=series.distinct_id_field,
    )


def series_hogql_modifiers(
    modifiers: HogQLQueryModifiers, series: EventsNode | ActionsNode | DataWarehouseNode | GroupNode
) -> HogQLQueryModifiers:
    """Modifiers that map the warehouse table of `series` to the fields of `series`.

    The database maps one `timestamp`, `id` and `distinct_id` per warehouse table, and the last
    modifier for a table wins. When two series read the same table with different fields, the
    other series must not overwrite the mapping of this series. Returns `modifiers` unchanged
    when no other series conflicts, so that the caller can keep a shared database.
    """
    if not isinstance(series, DataWarehouseNode) or not modifiers.dataWarehouseEventsModifiers:
        return modifiers

    own_modifier = data_warehouse_events_modifier(series)
    if all(
        modifier == own_modifier
        for modifier in modifiers.dataWarehouseEventsModifiers
        if modifier.table_name == series.table_name
    ):
        return modifiers

    other_tables = [
        modifier for modifier in modifiers.dataWarehouseEventsModifiers if modifier.table_name != series.table_name
    ]
    return modifiers.model_copy(update={"dataWarehouseEventsModifiers": [*other_tables, own_modifier]})
