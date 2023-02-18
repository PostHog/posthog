from datetime import timedelta
from typing import Dict, List, Literal, Tuple, Union

from posthog.cache_utils import cache_for
from posthog.models.property import PropertyName, TableColumn, TableWithProperties

ColumnName = str

TablesWithMaterializedColumns = Union[TableWithProperties, Literal["session_recording_events"]]


@cache_for(timedelta(minutes=15))
def get_materialized_columns(
    table: TablesWithMaterializedColumns,
) -> Dict[Tuple[PropertyName, TableColumn], ColumnName]:
    return {}


def materialize(
    table: TableWithProperties,
    property: PropertyName,
    column_name=None,
    table_column: TableColumn = "properties",
    create_minmax_index=False,
) -> None:
    pass


def backfill_materialized_columns(
    table: TableWithProperties,
    properties: List[Tuple[PropertyName, TableColumn]],
    backfill_period: timedelta,
    test_settings=None,
) -> None:
    pass
