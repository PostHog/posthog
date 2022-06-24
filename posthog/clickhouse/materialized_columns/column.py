from datetime import timedelta
from typing import Dict, List, Literal, Union

from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.clickhouse.materialized_columns.util import cache_for
from posthog.models.property import PropertyName, TableWithProperties

ColumnName = str

TablesWithMaterializedColumns = Union[TableWithProperties, Literal["session_recording_events"]]

TRIM_AND_EXTRACT_PROPERTY = trim_quotes_expr("JSONExtractRaw(properties, %(property)s)")


@cache_for(timedelta(minutes=15))
def get_materialized_columns(table: TablesWithMaterializedColumns) -> Dict[PropertyName, ColumnName]:
    return {}


def materialize(table: TableWithProperties, property: PropertyName, column_name=None) -> None:
    pass


def backfill_materialized_columns(
    table: TableWithProperties, properties: List[PropertyName], backfill_period: timedelta, test_settings=None
) -> None:
    pass
