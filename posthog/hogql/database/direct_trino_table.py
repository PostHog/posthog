from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.database.models import FieldOrTable
from posthog.hogql.errors import QueryError


class DirectTrinoTable(DirectSQLTable):
    trino_catalog: str
    trino_schema: str
    trino_table_name: str

    # Trino resolves unquoted identifiers case-insensitively, but the printer quotes canonical
    # names. Resolve the user's field spelling to the discovered column name before printing it.
    def _canonical_field_key(self, name: str | int) -> str | None:
        target = str(name).lower()
        return next((key for key in self.fields if key.lower() == target), None)

    def has_field(self, name: str | int) -> bool:
        return super().has_field(name) or self._canonical_field_key(name) is not None

    def get_field(self, name: str | int) -> FieldOrTable:
        if super().has_field(name):
            return super().get_field(name)
        key = self._canonical_field_key(name)
        if key is not None:
            return self.fields[key]
        return super().get_field(name)

    def to_printed_duckdb(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into DuckDB SQL")

    def to_printed_postgres(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into Postgres SQL")

    def to_printed_clickhouse(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into ClickHouse SQL")
