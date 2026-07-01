from typing import cast

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
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
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

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


def select_from_groups_table(requested_fields: dict[str, list[str | int]], key_limit: int | None = None):
    select = argmax_select(
        table_name="raw_groups",
        select_fields=requested_fields,
        group_fields=["index", "key"],
        argmax_field="updated_at",
    )
    if key_limit is not None:
        # Two-phase dedup: pick the N group keys cheaply, then argMax the heavy properties for only those keys.
        keys = parse_select("SELECT index, key FROM raw_groups GROUP BY index, key")
        keys.limit = ast.Constant(value=key_limit)
        # GLOBAL IN, not IN: groups is Distributed(rand()); a plain IN dedups per-shard over a subset of versions.
        select.where = ast.CompareOperation(
            op=ast.CompareOperationOp.GlobalIn,
            left=ast.Tuple(exprs=[ast.Field(chain=["index"]), ast.Field(chain=["key"])]),
            right=keys,
        )
    return select


def _resolved_table(table_type) -> object | None:
    # Unwrap alias wrappers (e.g. `FROM groups AS g`) to the underlying table.
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
        table_type = table_type.table_type
    return getattr(table_type, "table", None)


def _is_nonneg_int_constant(expr) -> bool:
    return isinstance(expr, ast.Constant) and isinstance(expr.value, int) and expr.value >= 0


class _WindowFunctionFinder(TraversingVisitor):
    # Window functions evade the order_by and has_aggregation guards but must see every group, so bail on them too.
    found: bool = False

    def visit(self, node):
        if not self.found:
            super().visit(node)

    def visit_select_query(self, node: ast.SelectQuery):
        pass  # a window inside a scalar subquery doesn't change this query's rows

    def visit_window_function(self, node: ast.WindowFunction):
        self.found = True


def _has_window_function(expr: ast.Expr) -> bool:
    finder = _WindowFunctionFinder()
    finder.visit(expr)
    return finder.found


def _bare_limit_key_count(node: SelectQuery) -> int | None:
    # Deferred: posthog.hogql.property imports database schema modules, so a top-level import here is circular.
    from posthog.hogql.property import has_aggregation  # noqa: PLC0415

    # Only safe for a bare `from groups limit N`; bail to the full dedup on anything that changes the surviving rows.
    if (
        node.select_from is None
        or node.select_from.next_join is not None
        or not _is_nonneg_int_constant(node.limit)
        or (node.offset is not None and not _is_nonneg_int_constant(node.offset))
        or node.where
        or node.prewhere
        or node.having
        or node.qualify
        or node.group_by
        or node.distinct
        or node.order_by
        or node.array_join_op
        or node.limit_by
        or node.limit_with_ties
        or node.limit_percent
        or any(has_aggregation(expr) for expr in node.select)
        or node.window_exprs
        or any(_has_window_function(expr) for expr in node.select)
        or not isinstance(_resolved_table(node.select_from.type), GroupsTable)
    ):
        return None

    # Guard above proved these are int Constants; cast so mypy sees `.value`.
    node_limit = cast(ast.Constant, node.limit)
    node_offset = cast(ast.Constant, node.offset)
    # +1 (mirrors persons): lets the outer LIMIT detect whether more rows exist.
    return node_limit.value + (node_offset.value if node.offset else 0) + 1


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
        return select_from_groups_table(table_to_add.fields_accessed, key_limit=_bare_limit_key_count(node))

    def to_printed_clickhouse(self, context):
        return "groups"

    def to_printed_hogql(self):
        return "groups"
