from rest_framework.exceptions import ValidationError

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DatabaseField, Table
from posthog.hogql.errors import QueryError

from posthog.hogql_queries.insights.query_context import QueryContextProtocol


def resolve_warehouse_field(database: Database, table_name: str, field_name: str) -> DatabaseField:
    table = database.get_table(table_name)
    field = table.fields.get(field_name)
    if field is None:
        raise ValidationError(detail=f"Unknown field {table_name}.{field_name}")
    if isinstance(field, Table):
        raise ValidationError(detail=f"{table_name}.{field_name} points to a table, not a field")
    assert isinstance(field, DatabaseField)
    return field


def resolve_warehouse_field_or_none(database: Database, table_name: str, field_name: str) -> DatabaseField | None:
    """Best-effort variant of resolve_warehouse_field, so callers that only want to inspect a
    column's type can leave error surfacing for unresolvable configs to their existing paths."""
    try:
        table = database.get_table(table_name)
    except QueryError:
        return None
    if not isinstance(table, Table):
        return None
    field = table.fields.get(field_name)
    return field if isinstance(field, DatabaseField) else None


class DataWarehouseSchemaMixin(QueryContextProtocol):
    _hogql_database: Database | None = None

    @property
    def hogql_database(self) -> Database:
        if self._hogql_database is None:
            # Lazily create once
            self._hogql_database = Database.create_for(
                team=self.context.team,
                user=self.context.user,
                modifiers=self.context.modifiers,
            )
        return self._hogql_database

    def get_warehouse_field(self, table_name: str, field_name: str) -> DatabaseField:
        return resolve_warehouse_field(self.hogql_database, table_name, field_name)
