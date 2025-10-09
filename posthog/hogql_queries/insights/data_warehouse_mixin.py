from posthog.schema import ActionsNode, DataWarehouseNode, EventsNode, SessionsNode

from posthog.hogql import ast

from posthog.models.filters.mixins.utils import cached_property


class DataWarehouseInsightQueryMixin:
    series: EventsNode | ActionsNode | DataWarehouseNode | SessionsNode

    @cached_property
    def _table_expr(self) -> ast.Field:
        if isinstance(self.series, DataWarehouseNode):
            return ast.Field(chain=[self.series.table_name])

        if isinstance(self.series, SessionsNode):
            return ast.Field(chain=["sessions"])

        return ast.Field(chain=["events"])
