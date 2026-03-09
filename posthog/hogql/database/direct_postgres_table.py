from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.errors import NotImplementedError
from posthog.hogql.escape_sql import escape_hogql_identifier


class DirectPostgresTable(FunctionCallTable):
    requires_args: bool = False
    postgres_schema: str
    postgres_table_name: str
    external_data_source_id: str

    def to_printed_hogql(self) -> str:
        return escape_hogql_identifier(self.name)

    def to_printed_clickhouse(self, context) -> str:
        raise NotImplementedError("Direct Postgres tables cannot be printed to ClickHouse SQL")
