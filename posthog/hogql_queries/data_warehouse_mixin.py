from posthog.schema import ActionsNode, DataWarehouseNode, EventsNode, GroupNode

from posthog.hogql import ast
from posthog.hogql.database.models import data_warehouse_timestamp_alias

from posthog.models.filters.mixins.utils import cached_property


class DataWarehouseInsightQueryMixin:
    series: EventsNode | ActionsNode | DataWarehouseNode | GroupNode

    @cached_property
    def _table_expr(self) -> ast.Field:
        if isinstance(self.series, DataWarehouseNode):
            return ast.Field(chain=[self.series.table_name])

        return ast.Field(chain=["events"])

    @cached_property
    def _timestamp_expr(self) -> ast.Field:
        """The column this series buckets and filters on.

        A data warehouse series declares its own `timestamp_field`, but the table's virtual
        `timestamp` field holds only the mapping applied last, so two series on one table would
        otherwise share a column. The hidden per-mapping alias keeps them apart.
        """
        if isinstance(self.series, DataWarehouseNode):
            return ast.Field(chain=[data_warehouse_timestamp_alias(self.series.timestamp_field)])

        return ast.Field(chain=["timestamp"])
