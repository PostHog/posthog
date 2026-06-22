from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.errors import QueryError


def escape_snowflake_identifier(identifier: str) -> str:
    if "%" in identifier:
        raise QueryError(f'The Snowflake identifier "{identifier}" is not permitted as it contains the "%" character')
    return '"' + identifier.replace('"', '""') + '"'


class DirectSnowflakeTable(DirectSQLTable):
    snowflake_catalog: str | None = None
    snowflake_schema: str
    snowflake_table_name: str

    def to_printed_snowflake(self, context) -> str:
        if not self.snowflake_schema.strip():
            raise QueryError("Direct Snowflake tables require a schema name.")
        parts = []
        if self.snowflake_catalog:
            parts.append(escape_snowflake_identifier(self.snowflake_catalog))
        parts.extend(
            [
                escape_snowflake_identifier(self.snowflake_schema),
                escape_snowflake_identifier(self.snowflake_table_name),
            ]
        )
        return ".".join(parts)

    def to_printed_postgres(self, context) -> str:
        raise QueryError("Direct Snowflake tables cannot be printed into Postgres SQL")

    def to_printed_clickhouse(self, context) -> str:
        raise QueryError("Direct Snowflake tables cannot be printed into ClickHouse SQL")
