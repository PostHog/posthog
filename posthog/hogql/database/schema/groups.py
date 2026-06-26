from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.lazy_join_tags import GROUPS_REVENUE_ANALYTICS
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyJoin,
    LazyJoinToAdd,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)
from posthog.hogql.database.schema.groups_revenue_analytics import GroupsRevenueAnalyticsTable
from posthog.hogql.errors import ResolutionError

GROUPS_TABLE_FIELDS: dict[str, FieldOrTable] = {
    "index": IntegerDatabaseField(
        name="group_type_index",
        nullable=False,
        description="Group type index (0-4); identifies which group type this row belongs to, matching `events.$group_N`.",
    ),
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "key": StringDatabaseField(
        name="group_key",
        nullable=False,
        description="Unique key for the group within its group type; join target for `events.$group_N`.",
    ),
    "created_at": DateTimeDatabaseField(
        name="created_at", nullable=False, description="When the group was first created in PostHog."
    ),
    "updated_at": DateTimeDatabaseField(
        name="_timestamp",
        nullable=False,
        description="When this group row was last written (ingestion timestamp); used to pick the latest version.",
    ),
    "properties": StringJSONDatabaseField(
        name="group_properties",
        nullable=False,
        description="JSON map of group properties (latest known values). Access keys with `properties.name` etc.",
    ),
    "revenue_analytics": LazyJoin(
        from_field=["key"],
        join_table=GroupsRevenueAnalyticsTable(),
        resolver=GROUPS_REVENUE_ANALYTICS,
    ),
}


def select_from_groups_table(requested_fields: dict[str, list[str | int]]):
    select = argmax_select(
        table_name="raw_groups",
        select_fields=requested_fields,
        group_fields=["index", "key"],
        argmax_field="updated_at",
    )
    # GROUP BY (index, key) is a prefix of the table ORDER BY (team_id, group_type_index, group_key) once team_id is
    # pinned by the mandatory WHERE, so ClickHouse can aggregate in sort order and finalize each group as it goes
    # instead of buffering an argMax state (carrying the full group_properties blob) for every group at once.
    select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
    return select


def _resolved_table(table_type) -> object | None:
    # Unwrap alias wrappers (e.g. `FROM groups AS g`) to the underlying table, so an aliased select is still
    # recognised as a direct groups select.
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
        table_type = table_type.table_type
    return getattr(table_type, "table", None)


def _push_limit_into_groups_dedup(select: SelectQuery, node: SelectQuery) -> None:
    # When directly selecting from `groups` with a LIMIT and nothing that changes which rows survive, copy the limit
    # into the dedup so in-order aggregation can stop after enough groups rather than scanning the whole team. Skip
    # anything that could change which/how many rows survive the limit: a WHERE/PREWHERE (a premature inner LIMIT
    # would drop rows the outer filter wanted), an ORDER BY (the limit would keep the wrong groups), a DISTINCT or
    # GROUP BY (could collapse the limited rows below the requested count), LIMIT BY/WITH TIES/PERCENT, or a
    # non-constant LIMIT/OFFSET. Without the pushdown the query is still correct and still memory-bounded by
    # optimize_aggregation_in_order; we only forgo early termination.
    #
    # `next_join` only catches explicit joins in the FROM -- the `revenue_analytics` lazy join is attached to `node`
    # after this runs, so the pushdown fires through it. That's correct because it is a row-preserving LEFT JOIN
    # (it never drops or filters a groups row), so any N groups plus their joined data is still a valid answer. A
    # future groups lazy join that is INNER or filters the left side would need to be excluded here.
    if (
        node.select_from is None
        or node.select_from.next_join is not None
        or not isinstance(node.limit, ast.Constant)
        or (node.offset is not None and not isinstance(node.offset, ast.Constant))
        or node.where
        or node.prewhere
        or node.group_by
        or node.distinct
        or node.order_by
        or node.limit_by
        or node.limit_with_ties
        or node.limit_percent
        or not isinstance(_resolved_table(node.select_from.type), GroupsTable)
    ):
        return

    offset = node.offset.value if isinstance(node.offset, ast.Constant) else 0
    # +1 mirrors persons: leaves room to detect whether more rows exist; the outer LIMIT trims the extra row.
    select.limit = ast.Constant(value=node.limit.value + offset + 1)
    select.offset = ast.Constant(value=0)


def join_with_group_n_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    # Which $group_N events column to join on; carried as plain data instead of being
    # captured in a closure so the LazyJoin (and the Database holding it) stays serializable.
    group_index = join_to_add.lazy_join.resolver_params.get("group_index")
    if group_index is None:
        raise ResolutionError("group_n lazy join requires resolver_params['group_index']")

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from person_distinct_ids")

    select_query = select_from_groups_table(join_to_add.fields_accessed)
    select_query.where = ast.CompareOperation(
        left=ast.Field(chain=["index"]),
        op=ast.CompareOperationOp.Eq,
        right=ast.Constant(value=group_index),
    )

    join_expr = ast.JoinExpr(table=select_query)
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, f"$group_{group_index}"]),
            right=ast.Field(chain=[join_to_add.to_table, "key"]),
        ),
        constraint_type="ON",
    )

    return join_expr


class RawGroupsTable(Table):
    description: str = (
        "Raw, un-deduplicated groups rows (one per update). Query `groups` instead unless you need to "
        "resolve the latest version of each group's properties yourself."
    )
    fields: dict[str, FieldOrTable] = GROUPS_TABLE_FIELDS

    def to_printed_clickhouse(self, context):
        return "groups"

    def to_printed_hogql(self):
        return "raw_groups"


class GroupsTable(LazyTable):
    description: str = (
        "Deduplicated groups (companies, organizations, etc.) in the project, with their latest properties. "
        "One row per (group type, group key). Join from events via `events.$group_N = groups.key`."
    )
    fields: dict[str, FieldOrTable] = GROUPS_TABLE_FIELDS

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        select = select_from_groups_table(table_to_add.fields_accessed)
        _push_limit_into_groups_dedup(select, node)
        return select

    def to_printed_clickhouse(self, context):
        return "groups"

    def to_printed_hogql(self):
        return "groups"
