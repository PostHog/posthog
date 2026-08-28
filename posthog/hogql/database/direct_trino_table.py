from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.database.models import FieldOrTable
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_trino_identifier


class DirectTrinoTable(DirectSQLTable):
    trino_catalog: str
    trino_schema: str
    trino_table_name: str

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

    def to_printed_trino(self, context) -> str:
        if not self.trino_catalog.strip():
            raise QueryError("Direct Trino tables require a catalog name.")
        if not self.trino_schema.strip():
            raise QueryError("Direct Trino tables require a schema name.")
        if not self.trino_table_name.strip():
            raise QueryError("Direct Trino tables require a table name.")
        return ".".join(
            escape_trino_identifier(part) for part in (self.trino_catalog, self.trino_schema, self.trino_table_name)
        )

    def to_printed_duckdb(self, context) -> str:
        raise QueryError("Trino direct connections support raw SQL only")

    def to_printed_postgres(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into Postgres SQL")

    def to_printed_clickhouse(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into ClickHouse SQL")
