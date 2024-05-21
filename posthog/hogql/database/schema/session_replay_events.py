from typing import Any
from posthog.hogql.ast import SelectQuery, JoinExpr
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    LazyJoin,
    FieldTraverser,
    DatabaseField,
    LazyTable,
    FieldOrTable,
)
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.log_entries import ReplayConsoleLogsLogEntriesTable
from posthog.hogql.database.schema.person_distinct_ids import (
    PersonDistinctIdsTable,
    join_with_person_distinct_ids_table,
)
from datetime import datetime

from posthog.hogql.database.schema.sessions import SessionsTable, select_from_sessions_table
from posthog.hogql.errors import ResolutionError


def join_replay_table_to_sessions_table(
    from_table: str, to_table: str, requested_fields: dict[str, Any], context: HogQLContext, node: SelectQuery
) -> JoinExpr:
    from posthog.hogql import ast

    if not requested_fields:
        raise ResolutionError("No fields requested from replay")

    # TODO i think this should be fixed in the session_where_clause_extractor so that it grabs time bounds for us
    join_expr = ast.JoinExpr(table=select_from_sessions_table(requested_fields, node, context))
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[from_table, "session_id"]),
            right=ast.Field(chain=[to_table, "session_id"]),
        )
    )
    return join_expr


def join_with_events_table(
    from_table: str,
    to_table: str,
    requested_fields: dict[str, list[str | int]],
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if "$session_id" not in requested_fields:
        requested_fields = {**requested_fields, "$session_id": ["$session_id"]}

    clamp_to_ttl = _clamp_to_ttl(["events", "timestamp"])

    select_fields: list[ast.Expr] = [
        ast.Alias(alias=name, expr=ast.Field(chain=chain)) for name, chain in requested_fields.items()
    ]
    select_query = SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        prewhere=clamp_to_ttl,
    )

    join_expr = ast.JoinExpr(table=select_query)
    join_expr.join_type = "JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[from_table, "session_id"]),
            right=ast.Field(chain=[to_table, "$session_id"]),
        )
    )

    return join_expr


def _clamp_to_ttl(chain: list[str | int]):
    from posthog.hogql import ast

    # TRICKY: tests can freeze time, if we use `now()` in the ClickHouse queries then the tests will fail
    # because the time in the query will be different from the time in the test
    # so we generate now in Python and pass it in
    now = datetime.now()
    clamp_to_ttl = ast.CompareOperation(
        op=ast.CompareOperationOp.GtEq,
        left=ast.Field(chain=chain),
        right=ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Sub,
            left=ast.Constant(value=now),
            # TODO be more clever about this date clamping
            right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=90)]),
        ),
    )
    return clamp_to_ttl


def join_with_console_logs_log_entries_table(
    from_table: str,
    to_table: str,
    requested_fields: dict[str, list[str | int]],
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if "log_source_id" not in requested_fields:
        requested_fields = {**requested_fields, "log_source_id": ["log_source_id"]}

    select_query = SelectQuery(
        select=[ast.Field(chain=chain) for chain in requested_fields.values()],
        select_from=ast.JoinExpr(table=ast.Field(chain=["console_logs_log_entries"])),
        # no need to clamp this table to a ttl, it only holds 12 weeks of logs anyway
    )

    join_expr = ast.JoinExpr(table=select_query)
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[from_table, "session_id"]),
            right=ast.Field(chain=[to_table, "log_source_id"]),
        )
    )

    return join_expr


RAW_ONLY_FIELDS = ["min_first_timestamp", "max_last_timestamp"]

SESSION_REPLAY_EVENTS_COMMON_FIELDS: dict[str, FieldOrTable] = {
    "session_id": StringDatabaseField(name="session_id"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "distinct_id": StringDatabaseField(name="distinct_id"),
    "min_first_timestamp": DateTimeDatabaseField(name="min_first_timestamp"),
    "max_last_timestamp": DateTimeDatabaseField(name="max_last_timestamp"),
    "first_url": DatabaseField(name="first_url"),
    "click_count": IntegerDatabaseField(name="click_count"),
    "keypress_count": IntegerDatabaseField(name="keypress_count"),
    "mouse_activity_count": IntegerDatabaseField(name="mouse_activity_count"),
    "active_milliseconds": IntegerDatabaseField(name="active_milliseconds"),
    "console_log_count": IntegerDatabaseField(name="console_log_count"),
    "console_warn_count": IntegerDatabaseField(name="console_warn_count"),
    "console_error_count": IntegerDatabaseField(name="console_error_count"),
    "size": IntegerDatabaseField(name="size"),
    "event_count": IntegerDatabaseField(name="event_count"),
    "message_count": IntegerDatabaseField(name="message_count"),
    "events": LazyJoin(
        from_field=["session_id"],
        join_table=EventsTable(),
        join_function=join_with_events_table,
    ),
    # this is so that HogQL properties e.g. on test account filters can find the correct column
    "properties": FieldTraverser(chain=["events", "properties"]),
    "pdi": LazyJoin(
        from_field=["distinct_id"],
        join_table=PersonDistinctIdsTable(),
        join_function=join_with_person_distinct_ids_table,
    ),
    "console_logs": LazyJoin(
        from_field=["session_id"],
        join_table=ReplayConsoleLogsLogEntriesTable(),
        join_function=join_with_console_logs_log_entries_table,
    ),
    "person": FieldTraverser(chain=["pdi", "person"]),
    "person_id": FieldTraverser(chain=["pdi", "person_id"]),
    "session": LazyJoin(
        from_field=["session_id"],
        join_table=SessionsTable(),
        join_function=join_replay_table_to_sessions_table,
    ),
}


class RawSessionReplayEventsTable(Table):
    fields: dict[str, FieldOrTable] = {
        **SESSION_REPLAY_EVENTS_COMMON_FIELDS,
        "min_first_timestamp": DateTimeDatabaseField(name="min_first_timestamp"),
        "max_last_timestamp": DateTimeDatabaseField(name="max_last_timestamp"),
        "first_url": DatabaseField(name="first_url"),
    }

    def avoid_asterisk_fields(self) -> list[str]:
        return ["first_url"]

    def to_printed_clickhouse(self, context):
        return "session_replay_events"

    def to_printed_hogql(self):
        return "raw_session_replay_events"


def select_from_session_replay_events_table(requested_fields: dict[str, list[str | int]]):
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
        "distinct_id": ast.Call(name="any", args=[ast.Field(chain=[table_name, "distinct_id"])]),
        "size": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "size"])]),
        "event_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "event_count"])]),
        "message_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "message_count"])]),
    }

    select_fields: list[ast.Expr] = []
    group_by_fields: list[ast.Expr] = []

    for name, chain in requested_fields.items():
        if name in RAW_ONLY_FIELDS:
            # these fields are accounted for by start_time and end_time, so can be skipped in the "not raw" table
            continue

        if name in aggregate_fields:
            select_fields.append(ast.Alias(alias=name, expr=aggregate_fields[name]))
        else:
            select_fields.append(ast.Alias(alias=name, expr=ast.Field(chain=[table_name, *chain])))
            group_by_fields.append(ast.Field(chain=[table_name, *chain]))

    return ast.SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=group_by_fields,
    )


class SessionReplayEventsTable(LazyTable):
    fields: dict[str, FieldOrTable] = {
        **{k: v for k, v in SESSION_REPLAY_EVENTS_COMMON_FIELDS.items() if k not in RAW_ONLY_FIELDS},
        "start_time": DateTimeDatabaseField(name="start_time"),
        "end_time": DateTimeDatabaseField(name="end_time"),
        "first_url": StringDatabaseField(name="first_url"),
    }

    def lazy_select(self, requested_fields: dict[str, list[str | int]], context, node):
        return select_from_session_replay_events_table(requested_fields)

    def to_printed_clickhouse(self, context):
        return "session_replay_events"

    def to_printed_hogql(self):
        return "session_replay_events"
