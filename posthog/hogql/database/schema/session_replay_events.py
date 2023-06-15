from typing import Dict, List

from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    LazyJoin,
    FieldTraverser,
    DatabaseField,
    LazyTable,
)
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdTable, join_with_person_distinct_ids_table


class RawSessionReplayEventsTable(Table):
    session_id: StringDatabaseField = StringDatabaseField(name="session_id")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")

    min_first_timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="min_first_timestamp")
    max_last_timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="max_last_timestamp")
    first_url: DatabaseField = DatabaseField(name="first_url")

    click_count: IntegerDatabaseField = IntegerDatabaseField(name="click_count")
    keypress_count: IntegerDatabaseField = IntegerDatabaseField(name="keypress_count")
    mouse_activity_count: IntegerDatabaseField = IntegerDatabaseField(name="mouse_activity_count")
    active_milliseconds: IntegerDatabaseField = IntegerDatabaseField(name="active_milliseconds")
    console_log_count: IntegerDatabaseField = IntegerDatabaseField(name="console_log_count")
    console_warn_count: IntegerDatabaseField = IntegerDatabaseField(name="console_warn_count")
    console_error_count: IntegerDatabaseField = IntegerDatabaseField(name="console_error_count")

    pdi: LazyJoin = LazyJoin(
        from_field="distinct_id",
        join_table=PersonDistinctIdTable(),
        join_function=join_with_person_distinct_ids_table,
    )

    person: FieldTraverser = FieldTraverser(chain=["pdi", "person"])
    person_id: FieldTraverser = FieldTraverser(chain=["pdi", "person_id"])

    def avoid_asterisk_fields(self) -> List[str]:
        return ["first_url"]

    def to_printed_clickhouse(self, context):
        return "session_replay_events"

    def to_printed_hogql(self):
        return "raw_session_replay_events"


def select_from_session_replay_events_table(requested_fields: Dict[str, List[str]]):
    from posthog.hogql import ast

    table_name = "raw_session_replay_events"

    aggregate_fields = {
        "start_time": ast.Call(name="min", args=[ast.Field(chain=[table_name, "min_first_timestamp"])]),
        "end_time": ast.Call(name="max", args=[ast.Field(chain=[table_name, "max_last_timestamp"])]),
        "first_url": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "first_url"])]),
        "click_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "click_count"])]),
        "keypress_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "keypress_count"])]),
        "mouse_activity_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "mouse_activity_count"])]),
        "active_milliseconds": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "active_milliseconds"])]),
        "console_log_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "console_log_count"])]),
        "console_warn_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "console_warn_count"])]),
        "console_error_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "console_error_count"])]),
    }

    select_fields: List[ast.Expr] = []
    group_by_fields: List[ast.Expr] = []

    for name, chain in requested_fields.items():
        if name in aggregate_fields:
            select_fields.append(ast.Alias(alias=name, expr=aggregate_fields[name]))
        else:
            select_fields.append(ast.Alias(alias=name, expr=ast.Field(chain=[table_name] + chain)))
            group_by_fields.append(ast.Field(chain=[table_name] + chain))

    return ast.SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=group_by_fields,
    )


class SessionReplayEventsTable(LazyTable):
    session_id: StringDatabaseField = StringDatabaseField(name="session_id")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")

    start_time: DateTimeDatabaseField = DateTimeDatabaseField(name="start_time")
    end_time: DateTimeDatabaseField = DateTimeDatabaseField(name="end_time")
    first_url: StringDatabaseField = StringDatabaseField(name="first_url")

    click_count: IntegerDatabaseField = IntegerDatabaseField(name="click_count")
    keypress_count: IntegerDatabaseField = IntegerDatabaseField(name="keypress_count")
    mouse_activity_count: IntegerDatabaseField = IntegerDatabaseField(name="mouse_activity_count")
    active_milliseconds: IntegerDatabaseField = IntegerDatabaseField(name="active_milliseconds")
    console_log_count: IntegerDatabaseField = IntegerDatabaseField(name="console_log_count")
    console_warn_count: IntegerDatabaseField = IntegerDatabaseField(name="console_warn_count")
    console_error_count: IntegerDatabaseField = IntegerDatabaseField(name="console_error_count")

    pdi: LazyJoin = LazyJoin(
        from_field="distinct_id",
        join_table=PersonDistinctIdTable(),
        join_function=join_with_person_distinct_ids_table,
    )

    person: FieldTraverser = FieldTraverser(chain=["pdi", "person"])
    person_id: FieldTraverser = FieldTraverser(chain=["pdi", "person_id"])

    def lazy_select(self, requested_fields: Dict[str, List[str]]):
        return select_from_session_replay_events_table(requested_fields)

    def to_printed_clickhouse(self, context):
        return "session_replay_events"

    def to_printed_hogql(self):
        return "session_replay_events"
