from abc import ABC, abstractmethod
from datetime import timedelta

from posthog.cache_utils import cache_for
from posthog.models.property import PropertyName, TableColumn, TableWithProperties
from posthog.settings import EE_AVAILABLE


ColumnName = str
TablesWithMaterializedColumns = TableWithProperties


class MaterializedColumnBackend(ABC):
    @abstractmethod
    def get_materialized_columns(
        self,
        table: TablesWithMaterializedColumns,
    ) -> dict[tuple[PropertyName, TableColumn], ColumnName]:
        raise NotImplementedError

    @abstractmethod
    def materialize(
        self,
        table: TableWithProperties,
        property: PropertyName,
        column_name=None,
        table_column: TableColumn = "properties",
        create_minmax_index=False,
    ) -> None:
        raise NotImplementedError


class DummyMaterializedColumnBackend(MaterializedColumnBackend):
    def get_materialized_columns(
        self,
        table: TablesWithMaterializedColumns,
    ) -> dict[tuple[PropertyName, TableColumn], ColumnName]:
        return {}

    def materialize(
        self,
        table: TableWithProperties,
        property: PropertyName,
        column_name=None,
        table_column: TableColumn = "properties",
        create_minmax_index=False,
    ) -> None:
        pass


if EE_AVAILABLE:
    from ee.clickhouse.materialized_columns.columns import EnterpriseMaterializedColumnBackend

    backend: MaterializedColumnBackend = EnterpriseMaterializedColumnBackend()
else:
    backend = DummyMaterializedColumnBackend()


get_materialized_columns = cache_for(timedelta(minutes=15))(backend.get_materialized_columns)
