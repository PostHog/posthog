import structlog

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsPersonSubTable, EventsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable

logger = structlog.get_logger(__name__)


def restricted_property_keys_for_table_type(table_type: ast.Type, context: HogQLContext) -> set[str]:
    """Top-level property names restricted by property-level access control for a table, or an empty set.

    Single source of truth shared by the ClickHouse printer (which JSONDropKeys-wraps the blob) and the property
    lowering / physical passes (which decline the materialized-column substitution for a restricted property, leaving
    the JSON-blob read the printer then scrubs to ''). Under-detecting here leaks the materialized value (PII); over-
    detecting only costs a mat-column optimization — so this is the security boundary and must never be reimplemented
    elsewhere.
    """
    if not context.restricted_properties:
        return set()
    if not isinstance(table_type, ast.BaseTableType):
        return set()

    # Deferred: PropertyDefinition pulls in the Django model layer; keep it off this module's import path.
    from products.event_definitions.backend.models.property_definition import PropertyDefinition  # noqa: PLC0415

    try:
        table = table_type.resolve_database_table(context)
    except Exception:
        # Fail-open: a resolution error here disables restriction enforcement on every path that consults this
        # function. Unreachable today (resolve_database_table is plain attribute access for all matched table types),
        # but log loudly so a future table type that can raise doesn't silently un-restrict properties.
        logger.warning("restricted_property_table_resolution_failed", table_type=type(table_type).__name__)
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
