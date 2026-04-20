from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_hogql_identifier, escape_postgres_identifier


class DirectPostgresTable(FunctionCallTable):
    requires_args: bool = False
    postgres_schema: str
    postgres_table_name: str
    external_data_source_id: str
    connection_metadata: dict[str, object] | None = None

    def to_printed_hogql(self) -> str:
        return escape_hogql_identifier(self.name)

    def to_printed_postgres(self, context) -> str:
        return (
            f"{escape_postgres_identifier(self.postgres_schema)}.{escape_postgres_identifier(self.postgres_table_name)}"
        )

    def to_printed_clickhouse(self, context) -> str:
        raise QueryError("Direct Postgres tables cannot be printed into ClickHouse SQL")
