from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_hogql_identifier, escape_postgres_identifier


class DirectPostgresTable(FunctionCallTable):
    requires_args: bool = False
    postgres_catalog: str | None = None
    postgres_schema: str
    postgres_table_name: str
    external_data_source_id: str
    connection_metadata: dict[str, object] | None = None

    def to_printed_hogql(self) -> str:
        return escape_hogql_identifier(self.name)

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
