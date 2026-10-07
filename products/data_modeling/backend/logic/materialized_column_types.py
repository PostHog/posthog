"""Which ClickHouse column types a materialized view cannot store."""

import re
from collections.abc import Iterable

# ClickHouse sends a Variant through ArrowStream as an Arrow dense union, and delta-rs refuses
# every union type. A Variant inside an Array, Map or Tuple still puts a union in the Arrow
# schema, so the pattern matches a Variant at any depth of the type.
_UNSTORABLE_TYPE = re.compile(r"\bVariant\(")


def unstorable_columns(columns: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """The (name, ClickHouse type) pairs whose type a materialized table cannot store, in input order."""
    return [(name, clickhouse_type) for name, clickhouse_type in columns if _UNSTORABLE_TYPE.search(clickhouse_type)]
