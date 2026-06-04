from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsPersonSubTable, EventsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable


def restricted_property_keys_for_table_type(table_type: ast.Type, context: HogQLContext) -> set[str]:
    """Top-level property names restricted by property-level access control for a table, or an empty set.

    Single source of truth shared by the ClickHouse printer (which JSONDropKeys-wraps the blob) and the property
    lowering pass (which routes a restricted property to that same blob read instead of its materialized column, so
    the value is scrubbed rather than leaked).
    """
    if not context.restricted_properties:
        return set()
    if not isinstance(table_type, ast.BaseTableType):
        return set()

    # Deferred: PropertyDefinition pulls in the Django model layer; keep it off this module's import path.
    from products.event_definitions.backend.models.property_definition import (  # noqa: PLC0415
        PropertyDefinition,
    )

    try:
        table = table_type.resolve_database_table(context)
    except Exception:
        return set()

    if isinstance(table, EventsPersonSubTable):
        prop_def_type = PropertyDefinition.Type.PERSON
    elif isinstance(table, EventsTable):
        prop_def_type = PropertyDefinition.Type.EVENT
    elif isinstance(table, (PersonsTable, RawPersonsTable)):
        prop_def_type = PropertyDefinition.Type.PERSON
    else:
        return set()

    return {name for name, ptype in context.restricted_properties if ptype == prop_def_type}
