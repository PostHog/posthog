from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_trino_identifier


class DirectTrinoTable(DirectSQLTable):
    trino_catalog: str
    trino_schema: str
    trino_table_name: str

    def to_printed_trino(self, context) -> str:
        if not self.trino_catalog.strip() or not self.trino_schema.strip():
            raise QueryError("Direct Trino tables require a catalog and schema name.")
        return ".".join(
            escape_trino_identifier(part) for part in (self.trino_catalog, self.trino_schema, self.trino_table_name)
        )

    def to_printed_duckdb(self, context) -> str:
        raise QueryError("Trino direct connections support raw SQL only")

    def to_printed_postgres(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into Postgres SQL")

    def to_printed_clickhouse(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into ClickHouse SQL")
