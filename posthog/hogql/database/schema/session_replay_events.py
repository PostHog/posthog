from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery, JoinExpr
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    Table,
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    LazyJoin,
    FieldTraverser,
    FieldOrTable,
    LazyJoinToAdd,
    StringArrayDatabaseField,
)
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.log_entries import ReplayConsoleLogsLogEntriesTable
from posthog.hogql.database.schema.person_distinct_ids import (
    PersonDistinctIdsTable,
    join_with_person_distinct_ids_table,
)
from datetime import datetime

from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1, select_from_sessions_table_v1
from posthog.hogql.database.schema.sessions_v2 import select_from_sessions_table_v2, session_id_to_session_id_v7_expr

from posthog.hogql.errors import ResolutionError


def join_replay_table_to_sessions_table_v1(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: SelectQuery
) -> JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from replay")

    join_expr = ast.JoinExpr(table=select_from_sessions_table_v1(join_to_add.fields_accessed, node, context))
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, "session_id"]),
            right=ast.Field(chain=[join_to_add.to_table, "session_id"]),
        ),
        constraint_type="ON",
    )
    return join_expr


def join_replay_table_to_sessions_table_v2(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: SelectQuery
) -> JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from replay")

    join_expr = ast.JoinExpr(table=select_from_sessions_table_v2(join_to_add.fields_accessed, node, context))
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=session_id_to_session_id_v7_expr(ast.Field(chain=[join_to_add.from_table, "session_id"])),
            right=ast.Field(chain=[join_to_add.to_table, "session_id_v7"]),
        ),
        constraint_type="ON",
    )
    return join_expr


def join_with_events_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    requested_fields = join_to_add.fields_accessed
    if "$session_id" not in join_to_add.fields_accessed:
        requested_fields = {**join_to_add.fields_accessed, "$session_id": ["$session_id"]}

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
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, "session_id"]),
            right=ast.Field(chain=[join_to_add.to_table, "$session_id"]),
        ),
        constraint_type="ON",
    )

    return join_expr


def _clamp_to_ttl(chain: list[str | int]):
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
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    requested_fields = join_to_add.fields_accessed
    if "log_source_id" not in join_to_add.fields_accessed:
        requested_fields = {**requested_fields, "log_source_id": ["log_source_id"]}

    select_query = SelectQuery(
        select=[ast.Field(chain=chain) for chain in requested_fields.values()],
        select_from=ast.JoinExpr(table=ast.Field(chain=["console_logs_log_entries"])),
        # no need to clamp this table to a ttl, it only holds 12 weeks of logs anyway
    )

    join_expr = ast.JoinExpr(table=select_query)
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, "session_id"]),
            right=ast.Field(chain=[join_to_add.to_table, "log_source_id"]),
        ),
        constraint_type="ON",
    )

    return join_expr


SESSION_REPLAY_EVENTS_COMMON_FIELDS: dict[str, FieldOrTable] = {
    "session_id": StringDatabaseField(name="session_id"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "distinct_id": StringDatabaseField(name="distinct_id"),
    "first_url": StringDatabaseField(name="first_url", nullable=True),
    "all_urls": StringArrayDatabaseField(name="all_urls"),
    "click_count": IntegerDatabaseField(name="click_count"),
    "active_milliseconds": IntegerDatabaseField(name="active_milliseconds"),
    "keypress_count": IntegerDatabaseField(name="keypress_count"),
    "mouse_activity_count": IntegerDatabaseField(name="mouse_activity_count"),
    "console_log_count": IntegerDatabaseField(name="console_log_count"),
    "console_warn_count": IntegerDatabaseField(name="console_warn_count"),
    "console_error_count": IntegerDatabaseField(name="console_error_count"),
    "size": IntegerDatabaseField(name="size"),
    "event_count": IntegerDatabaseField(name="event_count"),
    "message_count": IntegerDatabaseField(name="message_count"),
    "snapshot_source": StringDatabaseField(name="snapshot_source", nullable=True),
    "snapshot_library": StringDatabaseField(name="snapshot_library", nullable=True),
    "_timestamp": DateTimeDatabaseField(name="_timestamp"),
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
        join_table=SessionsTableV1(),
        join_function=join_replay_table_to_sessions_table_v1,
    ),
}


class RawSessionReplayEventsTable(Table):
    fields: dict[str, FieldOrTable] = {
        **SESSION_REPLAY_EVENTS_COMMON_FIELDS,
        "min_first_timestamp": DateTimeDatabaseField(name="min_first_timestamp"),
        "max_last_timestamp": DateTimeDatabaseField(name="max_last_timestamp"),
    }

    def avoid_asterisk_fields(self) -> list[str]:
        return [f for f in self.fields if f in ["session_id"]]

    def to_printed_clickhouse(self, context):
        return "session_replay_events"

    def to_printed_hogql(self):
        return "raw_session_replay_events"


class SessionReplayEventsTable(Table):
    fields: dict[str, FieldOrTable] = {
        **SESSION_REPLAY_EVENTS_COMMON_FIELDS,
        "start_time": DateTimeDatabaseField(name="start_time"),
        "end_time": DateTimeDatabaseField(name="end_time"),
    }

    def to_printed_clickhouse(self, context):
        return "grouped_session_replay_events"

    def to_printed_hogql(self):
        return "session_replay_events"
