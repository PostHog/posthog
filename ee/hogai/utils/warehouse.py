from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, serialize_database
from posthog.sync import database_sync_to_async


@database_sync_to_async
def serialize_database_schema(database: Database, hogql_context: HogQLContext):
    """Unified serialization of the database schema for the LLM."""
    serialized_database = serialize_database(hogql_context)
    schema_description = "\n\n".join(
        (
            f"Table `{table_name}` with fields:\n"
            + "\n".join(f"- {field.name} ({field.type})" for field in table.fields.values())
            for table_name, table in serialized_database.items()
            # Only the most important core tables, plus all warehouse tables
            if table_name in ["events", "groups", "persons"]
            or table_name in database.get_warehouse_tables()
            or table_name in database.get_views()
        )
    )
    return schema_description
