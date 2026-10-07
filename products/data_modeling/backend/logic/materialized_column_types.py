"""Which ClickHouse column types a materialized view cannot store."""

import re
from collections.abc import Iterable

from products.data_modeling.backend.facade.contracts import ClickHouseColumn

# ClickHouse sends a Variant through ArrowStream as an Arrow dense union, and delta-rs refuses
# every union type. A Variant inside an Array, Map or Tuple still puts a union in the Arrow
# schema, so the pattern matches a Variant at any depth of the type.
_UNSTORABLE_TYPE = re.compile(r"\bVariant\(")


def unstorable_columns(columns: Iterable[ClickHouseColumn]) -> list[ClickHouseColumn]:
    return [column for column in columns if _UNSTORABLE_TYPE.search(column.clickhouse_type)]
