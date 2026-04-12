from typing import Optional

from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    FieldOrTable,
    FunctionCallTable,
    IntegerDatabaseField,
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
