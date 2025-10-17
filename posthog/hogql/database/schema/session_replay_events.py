from datetime import datetime

from posthog.hogql.ast import JoinExpr, SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FieldTraverser,
    IntegerDatabaseField,
    LazyJoin,
    LazyJoinToAdd,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
)
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.log_entries import ReplayConsoleLogsLogEntriesTable
from posthog.hogql.database.schema.person_distinct_ids import (
    PersonDistinctIdsTable,
    join_with_person_distinct_ids_table,
)
from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1, select_from_sessions_table_v1
from posthog.hogql.database.schema.sessions_v2 import (
    select_from_sessions_table_v2,
    session_id_to_session_id_v7_as_uint128_expr,
)
from posthog.hogql.database.schema.sessions_v3 import select_from_sessions_table_v3, session_id_to_uint128_as_uuid_expr
from posthog.hogql.errors import ResolutionError


def join_replay_table_to_sessions_table_v1(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: SelectQuery
) -> JoinExpr:
    from posthog.hogql import ast

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
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from replay")

    join_expr = ast.JoinExpr(table=select_from_sessions_table_v2(join_to_add.fields_accessed, node, context))
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=session_id_to_session_id_v7_as_uint128_expr(ast.Field(chain=[join_to_add.from_table, "session_id"])),
            right=ast.Field(chain=[join_to_add.to_table, "session_id_v7"]),
        ),
        constraint_type="ON",
    )
    return join_expr


def join_replay_table_to_sessions_table_v3(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: SelectQuery
) -> JoinExpr:
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from replay")

    join_expr = ast.JoinExpr(table=select_from_sessions_table_v3(join_to_add.fields_accessed, node, context))
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=session_id_to_uint128_as_uuid_expr(ast.Field(chain=[join_to_add.from_table, "session_id"])),
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
    from posthog.hogql import ast

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
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

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


RAW_ONLY_FIELDS = ["min_first_timestamp", "max_last_timestamp"]

SESSION_REPLAY_EVENTS_COMMON_FIELDS: dict[str, FieldOrTable] = {
    "session_id": StringDatabaseField(name="session_id", nullable=False),
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
    "min_first_timestamp": DateTimeDatabaseField(name="min_first_timestamp", nullable=False),
    "max_last_timestamp": DateTimeDatabaseField(name="max_last_timestamp", nullable=False),
    "first_url": DatabaseField(name="first_url", nullable=True),
    "all_urls": DatabaseField(name="all_urls", nullable=True),
    "click_count": IntegerDatabaseField(name="click_count", nullable=False),
    "keypress_count": IntegerDatabaseField(name="keypress_count", nullable=False),
    "mouse_activity_count": IntegerDatabaseField(name="mouse_activity_count", nullable=False),
    "active_milliseconds": IntegerDatabaseField(name="active_milliseconds", nullable=False),
    "console_log_count": IntegerDatabaseField(name="console_log_count", nullable=False),
    "console_warn_count": IntegerDatabaseField(name="console_warn_count", nullable=False),
    "console_error_count": IntegerDatabaseField(name="console_error_count", nullable=False),
    "size": IntegerDatabaseField(name="size", nullable=False),
    "event_count": IntegerDatabaseField(name="event_count", nullable=False),
    "message_count": IntegerDatabaseField(name="message_count", nullable=False),
    "snapshot_source": StringDatabaseField(name="snapshot_source", nullable=True),
    "retention_period_days": IntegerDatabaseField(name="retention_period_days", nullable=True),
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
        "min_first_timestamp": DateTimeDatabaseField(name="min_first_timestamp", nullable=False),
        "max_last_timestamp": DateTimeDatabaseField(name="max_last_timestamp", nullable=False),
        "first_url": DatabaseField(name="first_url", nullable=True),
        "_timestamp": DateTimeDatabaseField(name="_timestamp", nullable=False),
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
        "all_urls": ast.Call(name="groupUniqArrayArray", args=[ast.Field(chain=[table_name, "all_urls"])]),
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
        "start_time": DateTimeDatabaseField(name="start_time", nullable=False),
        "end_time": DateTimeDatabaseField(name="end_time", nullable=False),
        "first_url": StringDatabaseField(name="first_url", nullable=True),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        return select_from_session_replay_events_table(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context):
        return "session_replay_events"

    def to_printed_hogql(self):
        return "session_replay_events"
