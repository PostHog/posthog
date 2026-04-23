"""Safe `SELECT` builder shared by every SQL source.

Assembles a read query from already-quoted identifiers (via an
`IdentifierQuoter`) and a value passed through as a driver-native parameter.
Values are **never** interpolated into the SQL string — they only ever leave
this module inside the returned `params` mapping, which the caller passes
straight to the DB cursor (`cursor.execute(sql, params)`).

Supported parameter placeholder styles match the drivers used today:

- `ParamStyle.PYFORMAT_NAMED` — `%(name)s` (psycopg, pymysql, pymssql).
- `ParamStyle.QMARK` — `?` positional (pyodbc/ADO-style).
- `ParamStyle.NUMERIC` — `:1`, `:2` … (snowflake-connector binding=numeric).
- `ParamStyle.NAMED` — `:name` (snowflake `qmark`-style, BigQuery
  parameterized queries).

Every existing hand-rolled `_build_query` in `mysql.py`, `mssql.py`,
`snowflake.py`, `bigquery.py`, `redshift.py`, `clickhouse.py` can be
expressed as a `SelectQueryBuilder` call.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Union

from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.sources.common.sql.identifiers import IdentifierQuoter

from products.data_warehouse.backend.types import IncrementalFieldType


class ParamStyle(enum.Enum):
    PYFORMAT_NAMED = "pyformat_named"
    QMARK = "qmark"
    NUMERIC = "numeric"
    NAMED = "named"


@dataclass(frozen=True)
class SafeSQL:
    """A SQL statement that never contains an interpolated value.

    `sql` is the statement text with driver-appropriate placeholders;
    `params` is the mapping (or positional list) the caller hands to the
    cursor. Together they form the only safe way to execute a query
    assembled by this package.
    """

    sql: str
    params: Union[dict[str, Any], list[Any]]


@dataclass(frozen=True)
class SelectQueryBuilder:
    """Builder for a `SELECT * FROM <table> [WHERE ...] [ORDER BY ...]` query.

    `quoter` controls how identifiers are quoted; `param_style` controls how
    parameter placeholders are emitted. Builder instances are frozen so the
    same builder can be reused across calls without risk of accidental state
    leak between sources.
    """

    quoter: IdentifierQuoter
    param_style: ParamStyle = ParamStyle.PYFORMAT_NAMED

    def select_all(
        self,
        *,
        schema: str,
        table_name: str,
        incremental_field: str | None = None,
        incremental_field_type: IncrementalFieldType | None = None,
        incremental_last_value: Any | None = None,
        extra_table_hint: str | None = None,
        order_by_incremental: bool = True,
    ) -> SafeSQL:
        """Build a full `SELECT * FROM schema.table` with optional incremental predicate.

        When `incremental_field` is provided, appends
        `WHERE <incremental_field> >= :last_value [ORDER BY <incremental_field> ASC]`.
        `incremental_last_value` falls back to the type's initial value so
        the semantics match today's `_build_query` implementations.

        `extra_table_hint` is appended verbatim after the table reference
        (e.g. MySQL `FORCE INDEX (...)`). Callers who use it must have
        already validated it through their quoter — the builder itself
        does not parse hint syntax.
        """
        table_ref = self.quoter.quote_qualified(schema, table_name)
        hint = f" {extra_table_hint}" if extra_table_hint else ""

        if incremental_field is None:
            return SafeSQL(sql=f"SELECT * FROM {table_ref}{hint}", params=self._empty_params())

        if incremental_field_type is None:
            raise ValueError("incremental_field_type is required when incremental_field is set")

        value = (
            incremental_last_value
            if incremental_last_value is not None
            else incremental_type_to_initial_value(incremental_field_type)
        )
        quoted_field = self.quoter.quote(incremental_field)
        placeholder, params = self._single_param("incremental_value", value)

        parts = [f"SELECT * FROM {table_ref}{hint}", f"WHERE {quoted_field} >= {placeholder}"]
        if order_by_incremental:
            parts.append(f"ORDER BY {quoted_field} ASC")

        return SafeSQL(sql=" ".join(parts), params=params)

    def _empty_params(self) -> dict[str, Any] | list[Any]:
        if self.param_style in (ParamStyle.PYFORMAT_NAMED, ParamStyle.NAMED):
            return {}
        return []

    def _single_param(self, name: str, value: Any) -> tuple[str, dict[str, Any] | list[Any]]:
        if self.param_style == ParamStyle.PYFORMAT_NAMED:
            return f"%({name})s", {name: value}
        if self.param_style == ParamStyle.NAMED:
            return f":{name}", {name: value}
        if self.param_style == ParamStyle.QMARK:
            return "?", [value]
        if self.param_style == ParamStyle.NUMERIC:
            return ":1", [value]
        raise ValueError(f"Unsupported param style: {self.param_style}")
