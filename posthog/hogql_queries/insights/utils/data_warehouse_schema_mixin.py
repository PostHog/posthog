from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DatabaseField

from posthog.hogql_queries.insights.query_context import QueryContextProtocol


class DataWarehouseSchemaMixin(QueryContextProtocol):
    _hogql_database: Database | None = None

    @property
    def hogql_database(self) -> Database:
        if self._hogql_database is None:
            # Lazily create once
            self._hogql_database = Database.create_for(
                team=self.context.team,
                modifiers=self.context.modifiers,
            )
        return self._hogql_database

    def get_warehouse_field(self, table_name: str, field_name: str) -> DatabaseField | None:
        table = self.hogql_database.get_table(table_name)
        return table.fields.get(field_name)
