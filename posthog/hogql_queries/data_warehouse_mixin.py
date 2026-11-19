from functools import cached_property

from posthog.schema import ActionsNode, DataWarehouseNode, EventsNode, GroupNode

from posthog.hogql import ast


class DataWarehouseInsightQueryMixin:
    series: EventsNode | ActionsNode | DataWarehouseNode | GroupNode

    @cached_property
    def _table_expr(self) -> ast.Field:
        if isinstance(self.series, DataWarehouseNode):
            return ast.Field(chain=[self.series.table_name])

        return ast.Field(chain=["events"])
