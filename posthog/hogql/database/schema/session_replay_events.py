from datetime import datetime

from posthog.hogql.ast import JoinExpr, SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.lazy_join_tags import (
    PERSON_DISTINCT_IDS,
    REPLAY_TO_CONSOLE_LOGS,
    REPLAY_TO_EVENTS,
    REPLAY_TO_SESSIONS_V1,
)
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
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdsTable
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
    "session_id": StringDatabaseField(
        name="session_id",
        nullable=False,
        description="Recording session identifier; matches `events.$session_id` and `sessions.session_id`.",
    ),
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "distinct_id": StringDatabaseField(
        name="distinct_id", nullable=False, description="Identifier of the user/device for the recording."
    ),
    "min_first_timestamp": DateTimeDatabaseField(
        name="min_first_timestamp",
        nullable=False,
        description="Earliest snapshot timestamp in this raw segment (in UTC); aggregated into `start_time`.",
    ),
    "max_last_timestamp": DateTimeDatabaseField(
        name="max_last_timestamp",
        nullable=False,
        description="Latest snapshot timestamp in this raw segment (in UTC); aggregated into `end_time`.",
    ),
    "first_url": DatabaseField(
        name="first_url", nullable=True, description="URL of the first page viewed in the session."
    ),
    "all_urls": DatabaseField(
        name="all_urls", nullable=True, description="Distinct set of URLs visited during the session."
    ),
    "click_count": IntegerDatabaseField(
        name="click_count", nullable=False, description="Total number of clicks in the session."
    ),
    "keypress_count": IntegerDatabaseField(
        name="keypress_count", nullable=False, description="Total number of keypresses in the session."
    ),
    "mouse_activity_count": IntegerDatabaseField(
        name="mouse_activity_count", nullable=False, description="Number of mouse activity events in the session."
    ),
    "active_milliseconds": IntegerDatabaseField(
        name="active_milliseconds",
        nullable=False,
        description="Time the user was actively interacting, in milliseconds (subset of total duration).",
    ),
    "console_log_count": IntegerDatabaseField(
        name="console_log_count", nullable=False, description="Number of console.log messages captured."
    ),
    "console_warn_count": IntegerDatabaseField(
        name="console_warn_count", nullable=False, description="Number of console.warn messages captured."
    ),
    "console_error_count": IntegerDatabaseField(
        name="console_error_count", nullable=False, description="Number of console.error messages captured."
    ),
    "size": IntegerDatabaseField(
        name="size", nullable=False, description="Size of the recording snapshot data in bytes."
    ),
    "event_count": IntegerDatabaseField(
        name="event_count", nullable=False, description="Number of rrweb snapshot events in the recording."
    ),
    "message_count": IntegerDatabaseField(
        name="message_count", nullable=False, description="Number of ingestion messages that made up this recording."
    ),
    "snapshot_source": StringDatabaseField(
        name="snapshot_source", nullable=True, description="Capture source of the recording, e.g. 'web' or 'mobile'."
    ),
    "snapshot_library": StringDatabaseField(
        name="snapshot_library", nullable=True, description="SDK/library that produced the recording snapshots."
    ),
    "retention_period_days": IntegerDatabaseField(
        name="retention_period_days", nullable=True, description="Number of days the recording is retained."
    ),
    "is_deleted": IntegerDatabaseField(
        name="is_deleted", nullable=False, description="Whether the recording has been deleted (1) or not (0)."
    ),
    "ai_tags_fixed": DatabaseField(
        name="ai_tags_fixed", nullable=True, description="AI-assigned tags from a fixed taxonomy."
    ),
    "ai_tags_freeform": DatabaseField(name="ai_tags_freeform", nullable=True, description="AI-assigned freeform tags."),
    "ai_highlighted": IntegerDatabaseField(
        name="ai_highlighted",
        nullable=False,
        description="Whether AI flagged this recording as noteworthy (1) or not (0).",
    ),
    "surfacing_score": DatabaseField(
        name="surfacing_score",
        nullable=True,
        description="AI-computed score ranking how worth surfacing the recording is.",
    ),
    "events": LazyJoin(
        from_field=["session_id"],
        join_table=EventsTable(),
        resolver=REPLAY_TO_EVENTS,
    ),
    # this is so that HogQL properties e.g. on test account filters can find the correct column
    "properties": FieldTraverser(chain=["events", "properties"]),
    "pdi": LazyJoin(
        from_field=["distinct_id"],
        join_table=PersonDistinctIdsTable(),
        resolver=PERSON_DISTINCT_IDS,
    ),
    "console_logs": LazyJoin(
        from_field=["session_id"],
        join_table=ReplayConsoleLogsLogEntriesTable(),
        resolver=REPLAY_TO_CONSOLE_LOGS,
    ),
    "person": FieldTraverser(chain=["pdi", "person"]),
    "person_id": FieldTraverser(chain=["pdi", "person_id"]),
    "session": LazyJoin(
        from_field=["session_id"],
        join_table=SessionsTableV1(),
        resolver=REPLAY_TO_SESSIONS_V1,
    ),
}


class RawSessionReplayEventsTable(Table):
    description: str = (
        "Raw per-segment aggregate state for session recordings; multiple rows per session. "
        "Query the deduplicated `session_replay_events` table to get one aggregated row per session."
    )
    fields: dict[str, FieldOrTable] = {
        **SESSION_REPLAY_EVENTS_COMMON_FIELDS,
        "min_first_timestamp": DateTimeDatabaseField(name="min_first_timestamp", nullable=False),
        "max_last_timestamp": DateTimeDatabaseField(name="max_last_timestamp", nullable=False),
        "first_url": DatabaseField(name="first_url", nullable=True),
        "_timestamp": DateTimeDatabaseField(name="_timestamp", nullable=False),
        "is_deleted": IntegerDatabaseField(name="is_deleted", nullable=False),
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
        "is_deleted": ast.Call(name="max", args=[ast.Field(chain=[table_name, "is_deleted"])]),
        "ai_tags_fixed": ast.Call(name="groupUniqArrayArray", args=[ast.Field(chain=[table_name, "ai_tags_fixed"])]),
        "ai_tags_freeform": ast.Call(
            name="groupUniqArrayArray", args=[ast.Field(chain=[table_name, "ai_tags_freeform"])]
        ),
        "ai_highlighted": ast.Call(name="max", args=[ast.Field(chain=[table_name, "ai_highlighted"])]),
        "surfacing_score": ast.Call(name="max", args=[ast.Field(chain=[table_name, "surfacing_score"])]),
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
    description: str = (
        "Aggregated metadata for session recordings (counts, URLs, console/activity stats); one row per session. "
        "Holds metadata only, not the recording snapshots. Join to events/persons via `session_id`/`distinct_id`."
    )
    fields: dict[str, FieldOrTable] = {
        **{k: v for k, v in SESSION_REPLAY_EVENTS_COMMON_FIELDS.items() if k not in RAW_ONLY_FIELDS},
        "start_time": DateTimeDatabaseField(
            name="start_time", nullable=False, description="Earliest snapshot timestamp across the session (in UTC)."
        ),
        "end_time": DateTimeDatabaseField(
            name="end_time", nullable=False, description="Latest snapshot timestamp across the session (in UTC)."
        ),
        "first_url": StringDatabaseField(
            name="first_url", nullable=True, description="URL of the first page viewed in the session."
        ),
        "is_deleted": IntegerDatabaseField(
            name="is_deleted", nullable=False, description="Whether the recording has been deleted (1) or not (0)."
        ),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        return select_from_session_replay_events_table(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context):
        return "session_replay_events"

    def to_printed_hogql(self):
        return "session_replay_events"
