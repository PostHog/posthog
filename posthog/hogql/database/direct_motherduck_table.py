from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.database.models import FieldOrTable
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_duckdb_identifier


class DirectMotherDuckTable(DirectSQLTable):
    motherduck_database: str
    motherduck_schema: str
    motherduck_table_name: str

    # DuckDB resolves identifiers case-insensitively while preserving stored case, so match a
    # HogQL field to its canonically-cased column regardless of how the user typed it.
    def _canonical_field_key(self, name: str | int) -> str | None:
        target = str(name).lower()
        for key in self.fields:
            if key.lower() == target:
                return key
        return None

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
        if not self.motherduck_database.strip() or not self.motherduck_schema.strip():
            raise QueryError("Direct MotherDuck tables require a database and schema name.")
        return ".".join(
            [
                escape_duckdb_identifier(self.motherduck_database),
                escape_duckdb_identifier(self.motherduck_schema),
                escape_duckdb_identifier(self.motherduck_table_name),
            ]
        )

    def to_printed_postgres(self, context) -> str:
        raise QueryError("Direct MotherDuck tables cannot be printed into Postgres SQL")

    def to_printed_clickhouse(self, context) -> str:
        raise QueryError("Direct MotherDuck tables cannot be printed into ClickHouse SQL")
