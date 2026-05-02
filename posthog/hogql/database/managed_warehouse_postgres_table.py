from __future__ import annotations

from typing import Optional

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.escape_sql import escape_hogql_identifier


class ManagedWarehousePostgresTable(FunctionCallTable):
    """A table promoted from a customer's managed DuckLake warehouse, queried
    live via ClickHouse's ``postgresql()`` table function.

    Connection details (host, port, database, user, password) come from the
    customer's ``DuckgresServer`` (per-org, in ``posthog/ducklake``) and are
    bound into the ClickHouse query as parameter values via
    ``context.add_sensitive_value()`` — never inlined into the rendered SQL.
    """

    requires_args: bool = False
    host: str
    port: int
    database: str
    user: str
    password: str
    schema: str
    postgres_table_name: str

    def to_printed_hogql(self) -> str:
        return escape_hogql_identifier(self.name)

    def to_printed_clickhouse(self, context: Optional[HogQLContext]) -> str:
        if context is None:
            raise ValueError("ManagedWarehousePostgresTable requires a HogQLContext for sensitive value binding")

        address = context.add_sensitive_value(f"{self.host}:{self.port}")
        database = context.add_sensitive_value(self.database)
        table = context.add_sensitive_value(self.postgres_table_name)
        user = context.add_sensitive_value(self.user)
        password = context.add_sensitive_value(self.password)
        schema = context.add_sensitive_value(self.schema)

        return f"postgresql({address}, {database}, {table}, {user}, {password}, {schema})"
