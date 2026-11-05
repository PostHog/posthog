from typing import cast

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.lazy_join_tags import GROUPS_REVENUE_ANALYTICS
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    FieldTraverser,
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
from posthog.hogql.visitor import TraversingVisitor, clone_expr

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


def select_from_groups_table(
    requested_fields: dict[str, list[str | int]], keys: ast.SelectQuery | ast.SelectSetQuery | None = None
) -> ast.SelectQuery:
    """``keys`` selects ``(index, key)`` pairs. When it is given, the dedup reads only those groups."""
    select = argmax_select(
        table_name="raw_groups",
        select_fields=requested_fields,
        group_fields=["index", "key"],
        argmax_field="updated_at",
    )
    if keys is not None:
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


def _bare_limit_key_count(node: SelectQuery) -> int | None:
    # Deferred: posthog.hogql.property imports database schema modules, so a top-level import here is circular.
    from posthog.hogql.property import has_aggregation, has_window_function  # noqa: PLC0415

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
        or any(has_window_function(expr) for expr in node.select)
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

    # If the outer query has a bounded prefilter on its source table (one that references `timestamp` —
    # which is the strongest signal we have that the matched set is small), push an additional
    # `group_key IN (SELECT $group_N FROM <source table> WHERE <outer prefilter>)` predicate into the
    # groups subquery. Without this filter, the LEFT JOIN materializes a hash table containing
    # every group of this type for the team, decompressing the (very wide) `group_properties`
    # blob row by row — on high-volume teams that's enough to OOM the whole query even when
    # only a handful of rows are actually being selected. With the filter, the hash table is
    # bounded by the distinct `$group_N` values present in the matched rows.
    outer_prefilter = _outer_prefilter(node, context, join_to_add)
    if outer_prefilter is not None:
        prefilter_where, prefilter_source = outer_prefilter
        key_subquery = ast.SelectQuery(
            select=[ast.Field(chain=[f"$group_{group_index}"])],
            select_from=prefilter_source,
            where=prefilter_where,
        )
        select_query.where = ast.And(
            exprs=[
                select_query.where,
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["key"]),
                    right=key_subquery,
                ),
            ]
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


# Static source-table aliases that resolve to a lazy join. Cloning a WHERE that references one
# into the inner `SELECT $group_N FROM <source table>` subquery re-triggers the same lazy join during
# resolution and recurses, so the prefilter is skipped in that case (see `_guarded_aliases`,
# which also picks up the per-project group-type-name aliases dynamically).
LAZY_JOIN_ALIASES = frozenset(
    {
        "person",
        "person_id",
        "pdi",
        "poe",
        "group_0",
        "group_1",
        "group_2",
        "group_3",
        "group_4",
        "goe_0",
        "goe_1",
        "goe_2",
        "goe_3",
        "goe_4",
        "session",
        "revenue_analytics",
    }
)


# The outer FROM tables whose WHERE the groups subquery can reuse, with the aliases each may carry besides the last
# part of its chain. The flag call rewrite reads flag_evaluations under the alias `events`.
_PREFILTER_SOURCE_ALIASES: dict[tuple[str, ...], frozenset[str]] = {
    ("events",): frozenset(),
    ("posthog", "flag_evaluations"): frozenset({"events"}),
}


def _guarded_aliases(context: HogQLContext, source_chain: list[str]) -> frozenset[str]:
    """Source-table aliases whose reference must skip the prefilter: the static lazy joins,
    plus every FieldTraverser on the source table (this catches the per-project group-type-name
    aliases like `organization`; the always-present `person`/`person_id` traversers are already in
    the static set, so the union just dedupes them)."""
    if context.database is None:
        return LAZY_JOIN_ALIASES
    try:
        source_table = context.database.get_table(source_chain)
    except Exception:
        return LAZY_JOIN_ALIASES
    traversers = frozenset(name for name, field in source_table.fields.items() if isinstance(field, FieldTraverser))
    return LAZY_JOIN_ALIASES | traversers


def _outer_prefilter(
    node: SelectQuery, context: HogQLContext, join_to_add: LazyJoinToAdd
) -> tuple[ast.Expr, ast.JoinExpr] | None:
    """
    Extract a clone of the outer query's WHERE that we can safely embed inside the groups
    join subquery, together with the FROM that the subquery reads. We only return it when:

    1. The outer's `FROM` is a table in `_PREFILTER_SOURCE_ALIASES`, either unaliased or aliased
       by the last part of its chain or by an alias listed for it. Anything else (custom alias like
       `FROM events AS e` in funnels, or a subquery) means the WHERE may reference symbols
       (`e.timestamp`, …) that don't exist in our inner `SELECT $group_N FROM <source table>`
       subquery — cloning a WHERE that names them would raise `Unable to resolve field` when the
       resolver walks the clone.
    2. The WHERE references the `timestamp` field — cheap heuristic for "the matched row
       set is bounded by a date range." Without that guard, a query whose WHERE is only
       `team_id = X` (or empty) would push a key subquery that scans every row for the
       team, which is strictly worse than no filter at all.
    3. The group join hangs off the outer FROM table, not a table the query joins explicitly. The outer
       WHERE bounds only the outer table's rows, so it says nothing about the group keys of a joined table.
    4. Every field in the WHERE resolves on the outer FROM table, directly or through its lazy joins and
       virtual tables. A field of an explicitly joined table (`e.event`) or a SELECT or ARRAY JOIN alias does
       not exist in the subquery. A clone that names one fails to compile. The check reads field types rather than
       `select_from.next_join`, because the lazy table resolver links each generated join into `next_join`
       before it builds the next one.
    5. The WHERE does not reference any lazy-join alias on the source table — including the
       per-project group-type-name aliases (e.g. `organization`) that resolve to `group_N`.
       Cloning a `group_N.X` / `organization.X` / `person.X` reference into the inner
       subquery would re-trigger the resolver on the same lazy join during inner-subquery
       resolution.
    """
    # Deferred: lazy_tables imports the resolver, which imports database schema modules — circular.
    from posthog.hogql.transforms.lazy_tables import find_field_chains, get_table_alias_for_lazy_join  # noqa: PLC0415

    where = node.where
    if where is None:
        return None

    select_from = node.select_from
    if select_from is None:
        return None
    table = select_from.table
    if not isinstance(table, ast.Field):
        return None
    source_chain = tuple(str(part) for part in table.chain)
    if source_chain not in _PREFILTER_SOURCE_ALIASES:
        return None
    alias = select_from.alias or source_chain[-1]
    if alias != source_chain[-1] and alias not in _PREFILTER_SOURCE_ALIASES[source_chain]:
        return None
    if get_table_alias_for_lazy_join(join_to_add.lazy_join_type) != alias:
        return None

    if not _references_timestamp(where):
        return None
    guarded_aliases = _guarded_aliases(context, list(source_chain))
    if any(
        _chain_hits_guarded_alias(chain, guarded_aliases, source_chain, alias) for chain in find_field_chains(where)
    ):
        return None
    if select_from.type is None or _references_another_table(where, select_from.type):
        return None
    # The subquery repeats the outer FROM's alias. A WHERE that qualifies a field by that alias then still resolves.
    return clone_expr(where), ast.JoinExpr(table=ast.Field(chain=list(table.chain)), alias=select_from.alias)


def _chain_hits_guarded_alias(chain: list, guarded: frozenset[str], source_chain: tuple[str, ...], alias: str) -> bool:
    # Condition #1 guarantees the outer FROM's qualifier is the source table, so a leading qualifier is
    # transparent: `events.organization.x` names the same lazy join as `organization.x`. Peel it before matching,
    # or the qualified form slips past the guard. The qualifier is the full chain, its last part, or the FROM alias.
    for qualifier in (list(source_chain), [source_chain[-1]], [alias]):
        if len(chain) > len(qualifier) and chain[: len(qualifier)] == qualifier:
            chain = chain[len(qualifier) :]
            break
    return bool(chain) and isinstance(chain[0], str) and chain[0] in guarded


class _TimestampReferenceFinder(TraversingVisitor):
    """Walks an expression to see whether it touches the `timestamp` field."""

    def __init__(self):
        super().__init__()
        self.found = False

    def visit_field(self, node):
        if node.chain and node.chain[-1] == "timestamp":
            self.found = True


def _references_timestamp(expr) -> bool:
    finder = _TimestampReferenceFinder()
    finder.visit(expr)
    return finder.found


class _ForeignFieldFinder(TraversingVisitor):
    """Walks an expression to see whether a field resolves outside the given table."""

    def __init__(self, table_type: ast.Type):
        super().__init__()
        self.table_type = table_type
        self.found = False

    def visit_field(self, node: ast.Field):
        if not _resolves_on(node.type, self.table_type):
            self.found = True

    # A nested query resolves its fields against its own FROM. The key subquery copies that FROM too.
    def visit_select_query(self, node: ast.SelectQuery):
        pass

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        pass


def _resolves_on(field_type: ast.Type | None, table_type: ast.Type) -> bool:
    if isinstance(field_type, ast.FieldAliasType):
        # The resolver types a lambda argument as an alias in the lambda's own scope. The key subquery copies the
        # lambda too. A SELECT or ARRAY JOIN alias does not exist in the key subquery.
        return isinstance(field_type.type, ast.LambdaArgumentType)
    if isinstance(field_type, ast.PropertyType):
        field_type = field_type.field_type
    if not isinstance(field_type, (ast.FieldType, ast.ExpressionFieldType, ast.FieldTraverserType)):
        return False
    owner = field_type.table_type
    while isinstance(owner, (ast.LazyJoinType, ast.VirtualTableType)):
        owner = owner.table_type
    return owner == table_type


def _references_another_table(expr: ast.Expr, table_type: ast.Type) -> bool:
    finder = _ForeignFieldFinder(table_type)
    finder.visit(expr)
    return finder.found


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
        key_limit = _bare_limit_key_count(node)
        if key_limit is None:
            return select_from_groups_table(table_to_add.fields_accessed)
        # Two-phase dedup: pick the N group keys cheaply, then argMax the heavy properties for only those keys.
        keys = parse_select("SELECT index, key FROM raw_groups GROUP BY index, key")
        keys.limit = ast.Constant(value=key_limit)
        return select_from_groups_table(table_to_add.fields_accessed, keys=keys)

    def to_printed_clickhouse(self, context):
        return "groups"

    def to_printed_hogql(self):
        return "groups"
