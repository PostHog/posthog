"""Schema-level row-filter predicates for SQL sources.

A row filter is a `{column, operator, value}` triple ANDed onto a source query's
`WHERE` clause so a sync only pulls matching rows. This module is the single,
driver-free safety boundary for that feature: it validates a filter against the
schema's discovered columns, classifies the column's native type, and coerces the
user-supplied value to a matching Python type.

Three rails make SQL injection impossible by construction:

1. **Column allowlist** — the column must exist in the schema's `schema_metadata`.
2. **Operator allowlist** — only `> >= < <= = !=` (with `==`/`<>` accepted as
   aliases). The operator emitted into SQL is looked up from `_CANONICAL_OPERATORS`,
   never passed through from user input.
3. **Typed value** — the value is validated against the column's
   `ColumnTypeCategory` and coerced to the right Python type, then always leaves as
   a *bound parameter* (never string-interpolated). The render helpers here emit
   placeholders only; the matching value goes in the returned params.

Identifier quoting is delegated to an `IdentifierQuoter` (the existing allowlist
boundary), so column names are validated and quoted the same way as everywhere else.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from posthog.temporal.data_imports.sources.common.sql.identifiers import IdentifierQuoter
from posthog.temporal.data_imports.sources.common.sql.metadata import extract_available_column_names


class RowFilterValidationError(ValueError):
    """Raised when a row filter fails validation (bad column, operator, or value type)."""


class ColumnTypeCategory(enum.Enum):
    """Coarse type category a column's native `data_type` maps onto.

    Used to decide how a filter value must be typed. `UNKNOWN` is a hard
    failure — we refuse to filter on a column whose type we can't safely
    classify, because we can't validate the value against it.
    """

    INTEGER = "integer"
    NUMERIC = "numeric"
    STRING = "string"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP = "timestamp"
    UNKNOWN = "unknown"


class RowFilter(TypedDict):
    """A row filter as it is persisted on the schema (raw JSON shape)."""

    column: str
    operator: str
    value: Any


@dataclass(frozen=True)
class ValidatedRowFilter:
    """A row filter after validation: canonical operator + coerced, typed value."""

    column: str
    operator: str
    value: Any
    category: ColumnTypeCategory


# The only operators that may reach SQL. Input aliases are normalized to these;
# the emitted operator is always one of these literals, never user input.
_CANONICAL_OPERATORS = frozenset({">", ">=", "<", "<=", "=", "!="})
_OPERATOR_ALIASES = {"==": "=", "<>": "!="}

MAX_ROW_FILTERS = 20


def normalize_operator(operator: Any) -> str:
    """Return the canonical operator for `operator`, or raise.

    Accepts the six canonical operators plus the `==` and `<>` aliases. Anything
    else (including non-strings) raises — the result is guaranteed to be a member
    of `_CANONICAL_OPERATORS`, so callers can interpolate it directly.
    """
    if not isinstance(operator, str):
        raise RowFilterValidationError(f"Operator must be a string, got {type(operator).__name__}")
    candidate = _OPERATOR_ALIASES.get(operator.strip(), operator.strip())
    if candidate not in _CANONICAL_OPERATORS:
        allowed = ", ".join(sorted(_CANONICAL_OPERATORS))
        raise RowFilterValidationError(f"Unsupported operator {operator!r}. Allowed operators: {allowed}")
    return candidate


def _strip_nullable_wrappers(data_type: str) -> str:
    """Unwrap ClickHouse `Nullable(...)` / `LowCardinality(...)` wrappers."""
    current = data_type.strip()
    while True:
        if current.startswith("Nullable(") and current.endswith(")"):
            current = current[len("Nullable(") : -1].strip()
        elif current.startswith("LowCardinality(") and current.endswith(")"):
            current = current[len("LowCardinality(") : -1].strip()
        else:
            return current


def _strip_type_params(data_type: str) -> str:
    """Drop trailing parameters, e.g. `varchar(255)` -> `varchar`, `numeric(10,2)` -> `numeric`."""
    paren = data_type.find("(")
    base = data_type if paren == -1 else data_type[:paren]
    return base.strip()


# Type vocabularies harvested from every SQL source's incremental-field classifier
# (postgres, mysql, mssql, snowflake, bigquery, redshift, clickhouse), widened to
# cover the non-incremental types a user may legitimately filter on.
_INTEGER_TYPES = {
    "int",
    "int2",
    "int4",
    "int8",
    "int16",
    "int32",
    "int64",
    "int128",
    "int256",
    "integer",
    "smallint",
    "mediumint",
    "bigint",
    "tinyint",
    "byteint",
    "serial",
    "smallserial",
    "bigserial",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
    "uint128",
    "uint256",
}
_NUMERIC_TYPES = {
    "numeric",
    "decimal",
    "real",
    "double",
    "double precision",
    "float",
    "float4",
    "float8",
    "float32",
    "float64",
    "number",
    "money",
    "smallmoney",
    "bignumeric",
    "dec",
    "fixed",
}
_STRING_TYPES = {
    "char",
    "character",
    "character varying",
    "varchar",
    "varchar2",
    "nchar",
    "nvarchar",
    "nvarchar2",
    "text",
    "tinytext",
    "mediumtext",
    "longtext",
    "ntext",
    "string",
    "fixedstring",
    "clob",
    "nclob",
    "uuid",
    "uniqueidentifier",
    "name",
    "citext",
    "enum",
    "json",
    "jsonb",
}
_BOOLEAN_TYPES = {"bool", "boolean", "bit"}
_DATE_TYPES = {"date", "date32"}
_TIMESTAMP_TYPES = {
    "timestamp",
    "timestamptz",
    "timestamp with time zone",
    "timestamp without time zone",
    "datetime",
    "datetime2",
    "datetime64",
    "smalldatetime",
    "datetimeoffset",
}


def classify_column_type(data_type: Any) -> ColumnTypeCategory:
    """Map a driver-native `data_type` string onto a `ColumnTypeCategory`.

    Case-insensitive, after unwrapping ClickHouse `Nullable(...)` wrappers and
    dropping length/precision params. Prefix matches handle parameterized
    timestamp/datetime spellings (e.g. `timestamp(6)`, `DateTime64(3, 'UTC')`).
    Returns `UNKNOWN` for anything unrecognized.
    """
    if not isinstance(data_type, str) or not data_type.strip():
        return ColumnTypeCategory.UNKNOWN

    inner = _strip_nullable_wrappers(data_type)
    base = _strip_type_params(inner).lower()

    if base in _INTEGER_TYPES:
        return ColumnTypeCategory.INTEGER
    if base in _NUMERIC_TYPES:
        return ColumnTypeCategory.NUMERIC
    if base in _BOOLEAN_TYPES:
        return ColumnTypeCategory.BOOLEAN
    if base in _DATE_TYPES:
        return ColumnTypeCategory.DATE
    if base in _STRING_TYPES:
        return ColumnTypeCategory.STRING
    if base in _TIMESTAMP_TYPES or base.startswith("timestamp") or base.startswith("datetime"):
        return ColumnTypeCategory.TIMESTAMP
    return ColumnTypeCategory.UNKNOWN


def _coerce_integer(value: Any) -> int:
    if isinstance(value, bool):
        raise RowFilterValidationError("Expected an integer value, got a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise RowFilterValidationError(f"Expected an integer value, got non-integral {value!r}")
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            raise RowFilterValidationError(f"Expected an integer value, got {value!r}")
    raise RowFilterValidationError(f"Expected an integer value, got {type(value).__name__}")


def _coerce_numeric(value: Any) -> int | float | Decimal:
    if isinstance(value, bool):
        raise RowFilterValidationError("Expected a numeric value, got a boolean")
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            raise RowFilterValidationError(f"Expected a numeric value, got {value!r}")
    raise RowFilterValidationError(f"Expected a numeric value, got {type(value).__name__}")


def _coerce_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    raise RowFilterValidationError(f"Expected a string value, got {type(value).__name__}")


def _coerce_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    raise RowFilterValidationError(f"Expected a boolean value (true/false), got {value!r}")


def _coerce_date(value: Any) -> date:
    if not isinstance(value, str):
        raise RowFilterValidationError(f"Expected an ISO date string (YYYY-MM-DD), got {type(value).__name__}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise RowFilterValidationError(f"Expected an ISO date string (YYYY-MM-DD), got {value!r}")


def _coerce_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise RowFilterValidationError(f"Expected an ISO datetime string, got {type(value).__name__}")
    raw = value.strip()
    # Accept a trailing "Z" (UTC) which `fromisoformat` rejects before 3.11.
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        # A plain date is a valid timestamp boundary (midnight).
        try:
            return datetime.combine(date.fromisoformat(raw), datetime.min.time())
        except ValueError:
            raise RowFilterValidationError(f"Expected an ISO datetime string, got {value!r}")


_COERCERS = {
    ColumnTypeCategory.INTEGER: _coerce_integer,
    ColumnTypeCategory.NUMERIC: _coerce_numeric,
    ColumnTypeCategory.STRING: _coerce_string,
    ColumnTypeCategory.BOOLEAN: _coerce_boolean,
    ColumnTypeCategory.DATE: _coerce_date,
    ColumnTypeCategory.TIMESTAMP: _coerce_timestamp,
}


def _column_types(schema_metadata: dict[str, Any] | None) -> dict[str, str]:
    """Map column name -> native `data_type` from a `schema_metadata` row."""
    if not isinstance(schema_metadata, dict):
        return {}
    columns = schema_metadata.get("columns")
    if not isinstance(columns, list):
        return {}
    result: dict[str, str] = {}
    for column in columns:
        if (
            isinstance(column, dict)
            and isinstance(column.get("name"), str)
            and isinstance(column.get("data_type"), str)
        ):
            result[column["name"]] = column["data_type"]
    return result


def validate_and_coerce_row_filters(
    row_filters: Any,
    schema_metadata: dict[str, Any] | None,
) -> list[ValidatedRowFilter]:
    """Validate raw row filters against a schema's columns and coerce their values.

    Returns an empty list for `None`/empty input. Raises `RowFilterValidationError`
    if the structure is malformed, a column is unknown, an operator is disallowed,
    the column's type can't be classified, or a value doesn't match the column's type.
    """
    if row_filters is None:
        return []
    if not isinstance(row_filters, list):
        raise RowFilterValidationError("row_filters must be a list")
    if len(row_filters) > MAX_ROW_FILTERS:
        raise RowFilterValidationError(f"Too many row filters (max {MAX_ROW_FILTERS})")

    available_columns = extract_available_column_names(schema_metadata)
    column_types = _column_types(schema_metadata)

    validated: list[ValidatedRowFilter] = []
    for index, row_filter in enumerate(row_filters):
        if not isinstance(row_filter, dict):
            raise RowFilterValidationError(f"Row filter at index {index} must be an object")

        column = row_filter.get("column")
        if not isinstance(column, str) or not column:
            raise RowFilterValidationError(f"Row filter at index {index} is missing a column")
        if available_columns and column not in available_columns:
            raise RowFilterValidationError(f"Unknown column {column!r} for this schema")

        operator = normalize_operator(row_filter.get("operator"))

        data_type = column_types.get(column)
        category = classify_column_type(data_type)
        if category is ColumnTypeCategory.UNKNOWN:
            raise RowFilterValidationError(
                f"Cannot filter on column {column!r}: its type {data_type!r} is not supported for filtering"
            )

        if "value" not in row_filter:
            raise RowFilterValidationError(f"Row filter on column {column!r} is missing a value")
        coerced = _COERCERS[category](row_filter["value"])

        validated.append(ValidatedRowFilter(column=column, operator=operator, value=coerced, category=category))

    return validated


def render_named_conditions(
    filters: list[ValidatedRowFilter],
    quoter: IdentifierQuoter,
    *,
    prefix: str = "row_filter",
) -> tuple[list[str], dict[str, Any]]:
    """Render filters as pyformat-named conditions (`%(name)s`) + a params dict.

    Used by MySQL/MSSQL-style drivers. Column identifiers are quoted via `quoter`
    (the allowlist boundary); values leave only as bound parameters.
    """
    conditions: list[str] = []
    params: dict[str, Any] = {}
    for index, row_filter in enumerate(filters):
        name = f"{prefix}_{index}"
        quoted = quoter.quote(row_filter.column)
        conditions.append(f"{quoted} {row_filter.operator} %({name})s")
        params[name] = row_filter.value
    return conditions, params


def render_positional_conditions(
    filters: list[ValidatedRowFilter],
    quoter: IdentifierQuoter,
) -> tuple[list[str], list[Any]]:
    """Render filters as positional conditions (`%s`) + an ordered values list.

    Used by Snowflake, where parameter order matters — the caller must append
    these values after any earlier positional params (e.g. the incremental value).
    """
    conditions: list[str] = []
    values: list[Any] = []
    for row_filter in filters:
        quoted = quoter.quote(row_filter.column)
        conditions.append(f"{quoted} {row_filter.operator} %s")
        values.append(row_filter.value)
    return conditions, values
