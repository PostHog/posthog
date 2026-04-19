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

# Shared across every HogQL view that reads session_replay_events. Keyed by
# session_id / distinct_id, these joins are the same regardless of whether the
# view is raw state-parts or a grouped one-row-per-session projection. Adding a
# new join here (e.g. a future issues lazy join) lights it up on every view
# without shotgun edits. database.py may rewrite individual entries per
# sessionTableVersion modifier — that mutates only the per-class `fields` dict,
# not this source.
_SESSION_REPLAY_LAZY_JOINS: dict[str, FieldOrTable] = {
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

# `all_urls`, `ai_tags_fixed`, `ai_tags_freeform` are deliberately declared as
# untyped `DatabaseField` rather than an array type. HogQL's current type system
# has no first-class array field, so the bare declaration signals "ClickHouse
# knows this is Array(String); HogQL treats it generically". Any typed downstream
# use must rely on HogQL functions (`has`, `arrayJoin`, length) which handle the
# CH side correctly.
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
    "snapshot_library": StringDatabaseField(name="snapshot_library", nullable=True),
    "retention_period_days": IntegerDatabaseField(name="retention_period_days", nullable=True),
    "is_deleted": IntegerDatabaseField(name="is_deleted", nullable=False),
    "ai_tags_fixed": DatabaseField(name="ai_tags_fixed", nullable=True),
    "ai_tags_freeform": DatabaseField(name="ai_tags_freeform", nullable=True),
    "ai_highlighted": IntegerDatabaseField(name="ai_highlighted", nullable=False),
    **_SESSION_REPLAY_LAZY_JOINS,
}


class RawSessionReplayEventsTable(Table):
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


# Rationale: the legacy and grouped aggregate dicts diverge on precisely the bugs
# the grouped view fixes — `any(distinct_id)` vs `argMax(distinct_id, …)`, missing
# `argMinMerge` on `snapshot_source`/`snapshot_library`, missing `max` on
# `retention_period_days`. Sharing a function with a flag would paper over those
# differences instead of expressing them. Two named factories keep the diff
# trivially visible. If a bug is fixed in one, grep the other.
def _legacy_session_replay_aggregates() -> dict:
    from posthog.hogql import ast

    table_name = "raw_session_replay_events"
    return {
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
    }


def select_from_session_replay_events_table(requested_fields: dict[str, list[str | int]]):
    from posthog.hogql import ast

    table_name = "raw_session_replay_events"
    aggregate_fields = _legacy_session_replay_aggregates()

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
        "is_deleted": IntegerDatabaseField(name="is_deleted", nullable=False),
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        return select_from_session_replay_events_table(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context):
        return "session_replay_events"

    def to_printed_hogql(self):
        return "session_replay_events"


GROUPED_SESSION_REPLAY_GROUP_BY_COLUMNS = ("session_id", "team_id")


def _grouped_session_replay_aggregates() -> dict:
    from posthog.hogql import ast

    table_name = "raw_session_replay_events"
    return {
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
        "size": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "size"])]),
        "event_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "event_count"])]),
        "message_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "message_count"])]),
        "snapshot_source": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "snapshot_source"])]),
        "snapshot_library": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "snapshot_library"])]),
        "retention_period_days": ast.Call(name="max", args=[ast.Field(chain=[table_name, "retention_period_days"])]),
        "is_deleted": ast.Call(name="max", args=[ast.Field(chain=[table_name, "is_deleted"])]),
        "ai_tags_fixed": ast.Call(name="groupUniqArrayArray", args=[ast.Field(chain=[table_name, "ai_tags_fixed"])]),
        "ai_tags_freeform": ast.Call(
            name="groupUniqArrayArray", args=[ast.Field(chain=[table_name, "ai_tags_freeform"])]
        ),
        "ai_highlighted": ast.Call(name="max", args=[ast.Field(chain=[table_name, "ai_highlighted"])]),
        "distinct_id": ast.Call(
            name="argMax",
            args=[
                ast.Field(chain=[table_name, "distinct_id"]),
                ast.Field(chain=[table_name, "max_last_timestamp"]),
            ],
        ),
    }


def select_from_grouped_session_replay_events_table(requested_fields: dict[str, list[str | int]]):
    from posthog.hogql import ast

    table_name = "raw_session_replay_events"
    aggregate_fields = _grouped_session_replay_aggregates()

    select_fields: list[ast.Expr] = []
    group_by_seen: set[str] = set()
    group_by_fields: list[ast.Expr] = []

    for alias, chain in requested_fields.items():
        # Only accept single-element chains. Multi-element chains reaching this
        # function would indicate an unresolved FieldTraverser or a brand-new HogQL
        # traversal path — neither should silently fall into GROUP BY, because
        # that is exactly how the legacy view ends up splitting sessions. Loud
        # rejection here catches the regression at resolve-time.
        column = chain[0] if len(chain) == 1 else None
        if column in GROUPED_SESSION_REPLAY_GROUP_BY_COLUMNS:
            select_fields.append(ast.Alias(alias=alias, expr=ast.Field(chain=[table_name, *chain])))
            if column not in group_by_seen:
                group_by_fields.append(ast.Field(chain=[table_name, column]))
                group_by_seen.add(column)
        elif column in aggregate_fields:
            select_fields.append(ast.Alias(alias=alias, expr=aggregate_fields[column]))
        else:
            raise ResolutionError(
                f"grouped_session_replay_events has no aggregation for {alias!r} (chain={chain!r}); "
                "every projected field must either be a GROUP BY column or have an aggregation defined"
            )

    # Always GROUP BY session_id and team_id, even when the caller did not project
    # them. Without this, a query like `SELECT click_count FROM grouped_session_replay_events`
    # would collapse every session into a single summed row. The printer also adds
    # a WHERE team_id filter, which makes team_id effectively constant — grouping
    # by it is redundant in that case but serves as a safety net for any context
    # where the filter is not applied (e.g. system queries, future optimisations).
    for required in GROUPED_SESSION_REPLAY_GROUP_BY_COLUMNS:
        if required not in group_by_seen:
            group_by_fields.append(ast.Field(chain=[table_name, required]))
            group_by_seen.add(required)

    return ast.SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=group_by_fields,
    )


class GroupedSessionReplayEventsTable(LazyTable):
    """One row per session view of the session_replay_events AggregatingMergeTree.

    Guarantees:
    - Exactly one row per (team_id, session_id) — no field can leak into GROUP BY.
    - `first_url`, `snapshot_source`, `snapshot_library` return readable strings
      via argMinMerge (not the underlying AggregateFunction state bytes).
    - Counters sum across state parts; `is_deleted`/`ai_highlighted` reduce via max;
      URL and AI-tag collections are deduped unions.

    Caveats:
    - `distinct_id` uses argMax(distinct_id, max_last_timestamp) which is
      best-effort: it picks the latest distinct_id while ClickHouse state parts
      remain unmerged. The underlying CH column is a plain VARCHAR (not an
      AggregateFunction), so once the storage layer merges parts it collapses
      via any(). For long-lived sessions the returned distinct_id is whatever
      CH happened to keep. Prefer `person_id` (resolved via `pdi`) when you need
      a stable identity. The stronger guarantee requires migrating the CH column
      to AggregateFunction(argMax, …) — tracked separately.
    """

    fields: dict[str, FieldOrTable] = {
        "session_id": StringDatabaseField(name="session_id", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
        "start_time": DateTimeDatabaseField(name="start_time", nullable=False),
        "end_time": DateTimeDatabaseField(name="end_time", nullable=False),
        "first_url": StringDatabaseField(name="first_url", nullable=True),
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
        "snapshot_library": StringDatabaseField(name="snapshot_library", nullable=True),
        "retention_period_days": IntegerDatabaseField(name="retention_period_days", nullable=True),
        "is_deleted": IntegerDatabaseField(name="is_deleted", nullable=False),
        "ai_tags_fixed": DatabaseField(name="ai_tags_fixed", nullable=True),
        "ai_tags_freeform": DatabaseField(name="ai_tags_freeform", nullable=True),
        "ai_highlighted": IntegerDatabaseField(name="ai_highlighted", nullable=False),
        **_SESSION_REPLAY_LAZY_JOINS,
    }

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        return select_from_grouped_session_replay_events_table(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context):
        return "session_replay_events"

    def to_printed_hogql(self):
        return "grouped_session_replay_events"
