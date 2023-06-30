from typing import Dict, List

from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    LazyTable,
    IntegerDatabaseField,
    StringDatabaseField,
    DateTimeDatabaseField,
    StringJSONDatabaseField,
    Table,
    FieldOrTable,
)

GROUPS_TABLE_FIELDS = {
    "index": IntegerDatabaseField(name="group_type_index"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "key": StringDatabaseField(name="group_key"),
    "created_at": DateTimeDatabaseField(name="created_at"),
    "updated_at": DateTimeDatabaseField(name="_timestamp"),
    "properties": StringJSONDatabaseField(name="group_properties"),
}


def select_from_groups_table(requested_fields: Dict[str, List[str]]):
    return argmax_select(
        table_name="raw_groups",
        select_fields=requested_fields,
        group_fields=["index", "key"],
        argmax_field="updated_at",
    )


class RawGroupsTable(Table):
    fields: Dict[str, FieldOrTable] = GROUPS_TABLE_FIELDS

    def to_printed_clickhouse(self, context):
        return "groups"

    def to_printed_hogql(self):
        return "groups"


class GroupsTable(LazyTable):
    fields: Dict[str, FieldOrTable] = GROUPS_TABLE_FIELDS

    def lazy_select(self, requested_fields: Dict[str, List[str]]):
        return select_from_groups_table(requested_fields)

    def to_printed_clickhouse(self, context):
        return "groups"

    def to_printed_hogql(self):
        return "groups"
