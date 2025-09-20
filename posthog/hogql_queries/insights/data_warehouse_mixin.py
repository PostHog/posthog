from posthog.schema import ActionsNode, DataWarehouseNode, EventsNode

from posthog.hogql import ast

from posthog.models.filters.mixins.utils import cached_property


class DataWarehouseInsightQueryMixin:
    series: EventsNode | ActionsNode | DataWarehouseNode

    @cached_property
    def _table_expr(self) -> ast.Field:
        if isinstance(self.series, DataWarehouseNode):
            return ast.Field(chain=[self.series.table_name])

        return ast.Field(chain=["events"])
