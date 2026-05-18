from typing import Optional

from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    FieldOrTable,
    FunctionCallTable,
    IntegerDatabaseField,
    UnknownDatabaseField,
)
from posthog.hogql.errors import QueryError


class RangeTable(FunctionCallTable, DANGEROUS_NoTeamIdCheckTable):
    """DuckDB/Postgres range(start, stop, step) table function. Returns a single column of integers."""

    fields: dict[str, FieldOrTable] = {
        "range": IntegerDatabaseField(name="range", nullable=False),
    }

    name: str = "range"
    min_args: Optional[int] = 1
    max_args: Optional[int] = 3

    def to_printed_clickhouse(self, context):
        raise QueryError("range() is not supported in ClickHouse dialect")

    def to_printed_postgres(self, context):
        return "range"

    def to_printed_hogql(self):
        return "range"


class GenerateSeriesTable(FunctionCallTable, DANGEROUS_NoTeamIdCheckTable):
    """DuckDB/Postgres generate_series(start, stop, step) table function. Returns a single column of integers."""

    fields: dict[str, FieldOrTable] = {
        "generate_series": IntegerDatabaseField(name="generate_series", nullable=False),
    }

    name: str = "generate_series"
    min_args: Optional[int] = 1
    max_args: Optional[int] = 3

    def to_printed_clickhouse(self, context):
        raise QueryError("generate_series() is not supported in ClickHouse dialect")

    def to_printed_postgres(self, context):
        return "generate_series"

    def to_printed_hogql(self):
        return "generate_series"


def build_opaque_function_call_table(name: str) -> "OpaqueFunctionCallTable":
    """Synthesize a table for a Postgres/DuckDB table-valued function discovered via introspection.

    The output column shape isn't introspected — we expose a single column named after the function
    with an unknown type. That covers the common single-column shapes (range, generate_series, unnest,
    jsonb_array_elements_text, regexp_split_to_table, …) without needing per-function schemas.
    """
    return OpaqueFunctionCallTable(
        name=name,
        fields={name: UnknownDatabaseField(name=name, nullable=True)},
    )


class OpaqueFunctionCallTable(FunctionCallTable, DANGEROUS_NoTeamIdCheckTable):
    """Generic table function for Postgres/DuckDB calls discovered via connection introspection.

    Used as a fallback when a `FROM some_func(args)` doesn't match a hand-rolled FunctionCallTable
    but the function name appears in the connection's available_table_functions.
    """

    fields: dict[str, FieldOrTable]
    name: str
    requires_args: bool = True
    min_args: Optional[int] = 1
    max_args: Optional[int] = None

    def to_printed_clickhouse(self, context):
        raise QueryError(f"Table function '{self.name}' is not supported in ClickHouse dialect")

    def to_printed_postgres(self, context):
        return self.name

    def to_printed_hogql(self):
        return self.name
