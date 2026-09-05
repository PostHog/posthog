import re
from collections.abc import Iterator

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import build_database_root_node
from posthog.hogql.database.models import StringJSONDatabaseField, Table, TableNode
from posthog.hogql.property_access_types import RestrictedProperty
from posthog.hogql.restricted_properties import RESTRICTABLE_JSON_BLOB_COLUMNS, restricted_property_keys_for_table_type

from posthog.constants import GROUP_TYPES_LIMIT

from products.event_definitions.backend.models.property_definition import PropertyDefinition

_GROUP_PROPERTIES_COLUMN = re.compile(r"group(\d+)_properties")

# A distinct restricted key per property class, so a table dispatched to the wrong class, or a group blob
# dispatched to the wrong index, comes back carrying the wrong key instead of passing on a non-empty set.
_EVENT_KEY = "restricted_event_property"
_PERSON_KEY = "restricted_person_property"
_GROUP_KEYS = tuple(f"restricted_group_{index}_property" for index in range(GROUP_TYPES_LIMIT))

# Every catalog blob the printer masks, and the keys it drops from each. Written out rather than derived
# from RESTRICTABLE_JSON_BLOB_COLUMNS, so that dropping a column name from that set fails here instead of
# quietly shrinking the walk below.
_MASKED_BLOBS: dict[str, frozenset[str]] = {
    "events.properties (EventsTable)": frozenset({_EVENT_KEY}),
    "events.person_properties (EventsPersonSubTable)": frozenset({_PERSON_KEY}),
    **{
        f"events.group{index}_properties (EventsGroupSubTable)": frozenset({_GROUP_KEYS[index]})
        for index in range(GROUP_TYPES_LIMIT)
    },
    "persons.properties (PersonsTable)": frozenset({_PERSON_KEY}),
    "raw_persons.properties (RawPersonsTable)": frozenset({_PERSON_KEY}),
    # The groups tables hold every group type, with the index in a column rather than in the blob's name, so
    # a read of one row's blob has to drop the restricted keys of all of them.
    "groups.group_properties (GroupsTable)": frozenset(_GROUP_KEYS),
    "raw_groups.group_properties (RawGroupsTable)": frozenset(_GROUP_KEYS),
    "groups.group_properties (PostgresTable)": frozenset(_GROUP_KEYS),
}

# Blob columns the dispatch returns no keys for. `properties` is a common column name, so most of these are
# a name collision: the contents are not a property class property-level access control knows about. Adding
# a branch for one means moving its entry into _MASKED_BLOBS.
_UNMASKED_BLOBS: frozenset[str] = frozenset(
    {
        # CRM account attributes, not person/event/group properties. Gated separately by the object-level
        # `access_scope="account"` on the table.
        "accounts.properties (PostgresTable)",
        # Metadata attached to an embedded item.
        "pg_embeddings.properties (PgEmbeddingsTable)",
        # Carries event properties, so unlike the two above this one is owed a branch. Tracked with
        # team-ai-observability, who own the table.
        "ai_events.properties (AiEventsTable)",
    }
)


def _restrictions_covering_every_property_class() -> set[RestrictedProperty]:
    restrictions = {
        RestrictedProperty(name=_EVENT_KEY, property_type=PropertyDefinition.Type.EVENT),
        RestrictedProperty(name=_PERSON_KEY, property_type=PropertyDefinition.Type.PERSON),
    }
    restrictions |= {
        RestrictedProperty(name=_GROUP_KEYS[index], property_type=PropertyDefinition.Type.GROUP, group_type_index=index)
        for index in range(GROUP_TYPES_LIMIT)
    }
    return restrictions


def _tables_in_node(node: TableNode) -> Iterator[Table]:
    if isinstance(node.table, Table):
        yield node.table
    for child in node.children.values():
        yield from _tables_in_node(child)


def _with_nested_tables(table: Table) -> Iterator[Table]:
    yield table
    for field in table.fields.values():
        if isinstance(field, Table):
            yield from _with_nested_tables(field)


def _restrictable_blob_columns(table: Table) -> set[str]:
    return {
        field.name
        for field in table.fields.values()
        if isinstance(field, StringJSONDatabaseField) and field.name in RESTRICTABLE_JSON_BLOB_COLUMNS
    }


def _blob_label(table: Table, column: str) -> str:
    return f"{table.to_printed_hogql()}.{column} ({type(table).__name__})"


def test_every_restrictable_blob_column_is_masked_with_the_keys_of_its_property_class():
    # The printer wraps a JSON blob in JSONDropKeys only when the column name is in
    # RESTRICTABLE_JSON_BLOB_COLUMNS *and* restricted_property_keys_for_table_type returns keys for the
    # table. The first half matches on a column name, the second on a table type, so either half can stop
    # covering a blob the other still covers, and the query still compiles and returns the restricted values.
    #
    # Comparing whole mappings holds both halves: a missing entry means a column left the name set, an entry
    # masking nothing means a catalog table has no dispatch branch, and a wrong value means a table reached
    # the wrong property class or group index.
    context = HogQLContext(team_id=1, restricted_properties=_restrictions_covering_every_property_class())

    masked: dict[str, frozenset[str]] = {}
    for table in _tables_in_node(build_database_root_node(include_posthog_tables=True)):
        for candidate in _with_nested_tables(table):
            for column in _restrictable_blob_columns(candidate):
                group_match = _GROUP_PROPERTIES_COLUMN.fullmatch(column)
                keys = frozenset(
                    restricted_property_keys_for_table_type(
                        ast.TableType(table=candidate),
                        context,
                        group_type_index=int(group_match.group(1)) if group_match else None,
                    )
                )
                # The catalog reaches most tables by more than one path, so tables sharing a label have to
                # agree on what is masked for the assertion below to speak for both.
                label = _blob_label(candidate, column)
                assert masked.setdefault(label, keys) == keys, f"{label} names blobs that mask different keys"

    assert masked == {**_MASKED_BLOBS, **dict.fromkeys(_UNMASKED_BLOBS, frozenset())}
