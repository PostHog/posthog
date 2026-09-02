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

# Blob columns the dispatch returns no keys for. `properties` is a common column name, so most of
# these are a name collision: the contents are not a property class property-level access control
# knows about. Adding a branch for one means removing its entry here.
_UNCOVERED_BLOB_COLUMNS = {
    # CRM account attributes, not person/event/group properties. Gated separately by the object-level
    # `access_scope="account"` on the table.
    ("accounts", "properties"),
    # Metadata attached to an embedded item.
    ("pg_embeddings", "properties"),
    # Carries event properties, so unlike the two above this one is owed a branch. Tracked with
    # team-ai-observability, who own the table.
    ("ai_events", "properties"),
}


def _restrictions_covering_every_property_class() -> set[RestrictedProperty]:
    restrictions = {
        RestrictedProperty(name="secret", property_type=PropertyDefinition.Type.EVENT),
        RestrictedProperty(name="secret", property_type=PropertyDefinition.Type.PERSON),
    }
    restrictions |= {
        RestrictedProperty(name="secret", property_type=PropertyDefinition.Type.GROUP, group_type_index=index)
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


def test_every_restrictable_blob_column_is_covered_by_a_dispatch_branch():
    # The printer wraps a JSON blob in JSONDropKeys only when the column name is in
    # RESTRICTABLE_JSON_BLOB_COLUMNS *and* restricted_property_keys_for_table_type returns keys for
    # the table. The first half matches on a column name, the second on a table type. So a table
    # that copies the events blob names without being added to the dispatch reads the blob
    # unscrubbed, and nothing says so: the query compiles and returns the restricted values.
    #
    # Asserting the exact set rather than a subset means covering one of these has to remove its
    # entry below, instead of leaving a stale claim behind.
    context = HogQLContext(team_id=1, restricted_properties=_restrictions_covering_every_property_class())

    unscrubbed: set[tuple[str, str]] = set()
    for table in _tables_in_node(build_database_root_node(include_posthog_tables=True)):
        for candidate in _with_nested_tables(table):
            for column in _restrictable_blob_columns(candidate):
                group_match = _GROUP_PROPERTIES_COLUMN.fullmatch(column)
                keys = restricted_property_keys_for_table_type(
                    ast.TableType(table=candidate),
                    context,
                    group_type_index=int(group_match.group(1)) if group_match else None,
                )
                if not keys:
                    unscrubbed.add((candidate.to_printed_hogql(), column))

    assert unscrubbed == _UNCOVERED_BLOB_COLUMNS
