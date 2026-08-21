import structlog

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.database.schema.events import EventsGroupSubTable, EventsPersonSubTable, EventsTable
from posthog.hogql.database.schema.groups import GroupsTable, RawGroupsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable

from posthog.constants import GROUP_TYPES_LIMIT

logger = structlog.get_logger(__name__)

# JSON blob columns that hold a restrictable property class, so the printer knows which blob reads to wrap in
# JSONDropKeys. Everything here must be covered by a branch in `restricted_property_keys_for_table_type`, and vice
# versa — a blob whose table type maps to a property class but whose column is missing here is read unscrubbed.
RESTRICTABLE_JSON_BLOB_COLUMNS: frozenset[str] = frozenset(
    {
        "properties",  # events.properties, persons.properties, groups.group_properties reads via the HogQL name
        "person_properties",  # EventsPersonSubTable (PoE mode)
        "group_properties",  # groups / raw_groups
        # EventsGroupSubTable (group-on-events mode) exposes each group type's blob on the events table.
        *(f"group{index}_properties" for index in range(GROUP_TYPES_LIMIT)),
    }
)


def restricted_property_keys_for_table_type(
    table_type: ast.Type, context: HogQLContext, *, group_type_index: int | None = None
) -> set[str]:
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

    # EventsPersonSubTable and EventsGroupSubTable are virtual tables over `events`, not EventsTable subclasses, but
    # they carry person/group properties — match them before the EventsTable branch either way.
    if isinstance(table, EventsPersonSubTable):
        prop_def_type = PropertyDefinition.Type.PERSON
    elif isinstance(table, EventsGroupSubTable):
        prop_def_type = PropertyDefinition.Type.GROUP
        group_type_index = table.group_index
    elif isinstance(table, EventsTable):
        prop_def_type = PropertyDefinition.Type.EVENT
    elif isinstance(table, (PersonsTable, RawPersonsTable)):
        prop_def_type = PropertyDefinition.Type.PERSON
    elif isinstance(table, (GroupsTable, RawGroupsTable)) or (
        isinstance(table, PostgresTable) and table.postgres_table_name == "posthog_group"
    ):
        prop_def_type = PropertyDefinition.Type.GROUP
    else:
        # PropertyDefinition.Type.SESSION is deliberately absent: the sessions tables expose each session property as
        # its own column rather than a JSON blob, so there is nothing for this function's callers to scrub. Restricting
        # a session property therefore has no query-time effect yet — enforcing it needs field-level denial, not a
        # blob-key drop.
        return set()

    return {
        restriction.name
        for restriction in context.restricted_properties
        if restriction.property_type == prop_def_type
        and (
            prop_def_type != PropertyDefinition.Type.GROUP
            or group_type_index is None
            or restriction.group_type_index == group_type_index
        )
    }
