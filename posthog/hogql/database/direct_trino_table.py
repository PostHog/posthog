from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.errors import QueryError


class DirectTrinoTable(DirectSQLTable):
    trino_catalog: str
    trino_schema: str
    trino_table_name: str

    def to_printed_duckdb(self, context) -> str:
        raise QueryError("Trino direct connections support raw SQL only")

    def to_printed_postgres(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into Postgres SQL")

    def to_printed_clickhouse(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into ClickHouse SQL")
