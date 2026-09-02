from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_clickhouse_identifier


class DirectClickHouseTable(DirectSQLTable):
    # ClickHouse namespaces a table as database.table (there is no separate catalog level).
    clickhouse_database: str
    clickhouse_table_name: str

    def to_printed_clickhouse(self, context) -> str:
        # Unlike the other direct tables (which target a different SQL dialect and raise here),
        # ClickHouse IS the printer's native dialect — so this renders the external table reference
        # that the direct-query executor runs against the external ClickHouse connection.
        parts = []
        if self.clickhouse_database.strip():
            parts.append(escape_clickhouse_identifier(self.clickhouse_database))
        parts.append(escape_clickhouse_identifier(self.clickhouse_table_name))
        return ".".join(parts)

    def to_printed_postgres(self, context) -> str:
        raise QueryError("Direct ClickHouse tables cannot be printed into Postgres SQL")

    def to_printed_mysql(self, context) -> str:
        raise QueryError("Direct ClickHouse tables cannot be printed into MySQL SQL")
