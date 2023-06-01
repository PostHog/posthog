from typing import Dict, List

from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    LazyTable,
    IntegerDatabaseField,
    StringDatabaseField,
    DateTimeDatabaseField,
    StringJSONDatabaseField,
    Table,
)


def select_from_groups_table(requested_fields: Dict[str, List[str]]):
    return argmax_select(
        table_name="raw_groups",
        select_fields=requested_fields,
        group_fields=["index", "key"],
        argmax_field="updated_at",
    )


class RawGroupsTable(Table):
    index: IntegerDatabaseField = IntegerDatabaseField(name="group_type_index")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")

    key: StringDatabaseField = StringDatabaseField(name="group_key")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    updated_at: DateTimeDatabaseField = DateTimeDatabaseField(name="_timestamp")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="group_properties")

    def clickhouse_table(self):
        return "groups"

    def hogql_table(self):
        return "groups"


class GroupsTable(LazyTable):
    index: IntegerDatabaseField = IntegerDatabaseField(name="group_type_index")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")

    key: StringDatabaseField = StringDatabaseField(name="group_key")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    updated_at: DateTimeDatabaseField = DateTimeDatabaseField(name="_timestamp")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="group_properties")

    def lazy_select(self, requested_fields: Dict[str, List[str]]):
        return select_from_groups_table(requested_fields)

    def clickhouse_table(self):
        return "groups"

    def hogql_table(self):
        return "groups"
