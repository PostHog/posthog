from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_postgres_identifier


class DirectPostgresTable(DirectSQLTable):
    postgres_catalog: str | None = None
    postgres_schema: str
    postgres_table_name: str

    def to_printed_postgres(self, context) -> str:
        parts = []
        postgres_catalog = self.postgres_catalog
        connection_metadata = (
            self.connection_metadata
            if isinstance(self.connection_metadata, dict)
            else getattr(context, "direct_postgres_connection_metadata", None)
        )

        if not postgres_catalog and isinstance(connection_metadata, dict):
            engine = connection_metadata.get("engine")
            database = connection_metadata.get("database")
            if engine == "duckdb" and isinstance(database, str) and database.strip():
                postgres_catalog = database.strip()

        if postgres_catalog:
            parts.append(escape_postgres_identifier(postgres_catalog))
        parts.append(escape_postgres_identifier(self.postgres_schema))
        parts.append(escape_postgres_identifier(self.postgres_table_name))
        return ".".join(parts)

    def to_printed_clickhouse(self, context) -> str:
        raise QueryError("Direct Postgres tables cannot be printed into ClickHouse SQL")
