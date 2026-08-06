from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from posthog.sync import database_sync_to_async


@database_sync_to_async
def serialize_database_schema(database: Database, hogql_context: HogQLContext):
    """Unified serialization of the database schema for the LLM."""

    # Simplify the schema description by only including the most important core tables, plus all warehouse tables and views.
    # `sessions` and `logs` are core query targets, and the `posthog.*` namespace holds tables (e.g. `posthog.ai_events`)
    # that are only reachable by their dotted name — without them here the model guesses field and table names.
    posthog_namespace_table_names = [
        name for name in database.get_posthog_table_names(include_hidden=True) if name.startswith("posthog.")
    ]
    serialized_database = database.serialize(
        hogql_context,
        include_only={
            "events",
            "groups",
            "persons",
            "sessions",
            "logs",
            *posthog_namespace_table_names,
            *database.get_warehouse_table_names(),
            *database.get_system_table_names(),
            *database.get_view_names(),
        },
        include_hidden_posthog_tables=True,
    )

    schema_description = "\n\n".join(
        (
            f"Table `{table_name}` with fields:\n"
            + "\n".join(f"- {field.name} ({field.type})" for field in table.fields.values())
            for table_name, table in serialized_database.items()
        )
    )

    return schema_description
