"""Which ClickHouse column types a materialized view cannot store."""

import re
from collections.abc import Iterable
from uuid import UUID

from products.data_modeling.backend.facade.contracts import ClickHouseColumn, UnstorableColumnTypeError
from products.data_modeling.backend.logic.saved_query_reads import get_saved_query_columns

# ClickHouse sends a Variant through ArrowStream as an Arrow dense union, and delta-rs refuses
# every union type. A Variant inside an Array, Map or Tuple still puts a union in the Arrow
# schema, so the pattern matches a Variant at any depth of the type.
_UNSTORABLE_TYPE = re.compile(r"\bVariant\(")
_QUOTED_TYPE_CONTENT = re.compile(r"'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`")


def unstorable_columns(columns: Iterable[ClickHouseColumn]) -> list[ClickHouseColumn]:
    return [
        column for column in columns if _UNSTORABLE_TYPE.search(_QUOTED_TYPE_CONTENT.sub("", column.clickhouse_type))
    ]


def check_saved_query_column_types(team_id: int, saved_query_id: UUID | str) -> None:
    unstorable = unstorable_columns(
        ClickHouseColumn(name=name, clickhouse_type=clickhouse_type)
        for name, clickhouse_type in get_saved_query_columns(team_id, saved_query_id).items()
    )
    if unstorable:
        raise UnstorableColumnTypeError(unstorable)
