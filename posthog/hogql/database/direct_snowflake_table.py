from posthog.hogql.database.direct_postgres_table import FunctionCallTable
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_hogql_identifier


class DirectSnowflakeTable(FunctionCallTable):
    requires_args: bool = False
    snowflake_schema: str
    snowflake_table_name: str
    external_data_source_id: str
    connection_metadata: dict[str, object] | None = None

    def to_printed_hogql(self) -> str:
        return escape_hogql_identifier(self.name)

    def to_printed_snowflake(self, context) -> str:
        if not self.snowflake_schema.strip():
            raise QueryError("Direct Snowflake tables require a schema name.")
        return ".".join(
            [
                escape_hogql_identifier(self.snowflake_schema),
                escape_hogql_identifier(self.snowflake_table_name),
            ]
        )

    def to_printed_postgres(self, context) -> str:
        raise QueryError("Direct Snowflake tables cannot be printed into Postgres SQL")

    def to_printed_clickhouse(self, context) -> str:
        raise QueryError("Direct Snowflake tables cannot be printed into ClickHouse SQL")
