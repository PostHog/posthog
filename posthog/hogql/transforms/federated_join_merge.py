"""Merge sibling aggregating LEFT JOINs over federated Postgres tables into one join.

A select like `accounts LEFT JOIN (agg₁) LEFT JOIN (agg₂) LEFT JOIN (agg₃)`, where each
right side is a `GROUP BY <key>` subquery over `postgresql(...)` reads joined on the same
base key, executes its federated scans sequentially, one per join. Rewriting the siblings
into a single join over `UNION ALL` branches re-grouped by the key lets ClickHouse run all
the scans inside one pipeline stage, so the per-scan Postgres COPY latencies overlap
instead of adding up.

The rewrite must reproduce LEFT JOIN default-fill semantics per column, so only three
column shapes are merged, and anything else makes the whole select ineligible, favoring
correctness over coverage:

- `count()` columns: padded with NULL in other branches, re-aggregated as
  `coalesce(max(col), 0)`, so a miss fills 0, matching the original non-nullable default.
- array columns: padded with `[]`, re-aggregated as `max(col)`: at most one branch holds
  a non-empty value, and a miss fills `[]`.
- nullable columns: padded with NULL, re-aggregated as `max(col)` (max skips NULLs), so a
  miss fills NULL. Non-nullable non-count scalars are rejected: their original join-miss
  default (`''`/`0`) can't be told apart from a real value after the union.
"""

from dataclasses import dataclass
from typing import Literal

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.resolver import ResolverFactory, resolve_types
from posthog.hogql.visitor import TraversingVisitor, clone_expr

MERGED_ALIAS = "__merged_aggregates"
MERGED_KEY = "__key"

_ARRAY_CALLS = {"groupArray", "arraySort", "arrayDistinct", "groupUniqArray"}

_ColumnKind = Literal["count", "array", "nullable"]


@dataclass
class _Candidate:
    prev: ast.JoinExpr
    join: ast.JoinExpr
    alias: str
    subquery: ast.SelectQuery
    key_name: str
    base_key_chain: tuple[str | int, ...]
    # (column alias, kind) per non-key select column
    columns: list[tuple[str, _ColumnKind]]


def merge_federated_aggregate_joins(
    node: _T_AST,
    context: HogQLContext,
    dialect: HogQLDialect,
    stack: list[ast.SelectQuery] | None = None,
    resolver_factory: ResolverFactory | None = None,
) -> _T_AST:
    if dialect != "clickhouse":
        return node

    finder = _SelectFinder()
    finder.visit(node)
    for select in finder.selects:
        _merge_in_select(select, context, dialect, resolver_factory)
    return node


class _SelectFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.selects: list[ast.SelectQuery] = []

    def visit_select_query(self, node: ast.SelectQuery):
        self.selects.append(node)
        super().visit_select_query(node)


def _table_is_federated(join_expr: ast.JoinExpr | None) -> bool:
    """Every table in the subquery's FROM chain must be a federated Postgres read.

    PostgresTable specifically, not any FunctionCallTable: S3-backed warehouse joins
    resolve their outer references through type shapes the alias rewriter doesn't
    handle, and their scans don't serialize the way the postgresql() reads do.
    """
    ptr = join_expr
    while ptr is not None:
        table_type = getattr(ptr.table, "type", None)
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            table_type = table_type.table_type
        if not isinstance(table_type, ast.TableType) or not isinstance(table_type.table, PostgresTable):
            return False
        ptr = ptr.next_join
    return True


def _classify_column(expr: ast.Expr) -> _ColumnKind | None:
    if isinstance(expr, ast.Call):
        if expr.name == "count":
            return "count"
        if expr.name in _ARRAY_CALLS:
            return "array"
    expr_type = getattr(expr, "type", None)
    constant_type = expr_type.return_type if isinstance(expr_type, ast.CallType) else expr_type
    if isinstance(constant_type, ast.ArrayType):
        return "array"
    if isinstance(constant_type, ast.ConstantType) and constant_type.nullable:
        return "nullable"
    return None


def _candidate_for_join(prev: ast.JoinExpr, join: ast.JoinExpr, base_alias: str) -> _Candidate | None:
    if join.join_type != "LEFT JOIN" or join.alias is None or not isinstance(join.table, ast.SelectQuery):
        return None
    constraint = join.constraint
    if constraint is None or constraint.constraint_type != "ON":
        return None
    compare = constraint.expr
    if not isinstance(compare, ast.CompareOperation) or compare.op != ast.CompareOperationOp.Eq:
        return None
    # The resolver wraps constraint fields in hidden aliases.
    sides = [side.expr if isinstance(side, ast.Alias) else side for side in (compare.left, compare.right)]
    if not all(isinstance(side, ast.Field) and len(side.chain) == 2 for side in sides):
        return None
    base_side = next((s for s in sides if isinstance(s, ast.Field) and s.chain[0] == base_alias), None)
    join_side = next((s for s in sides if isinstance(s, ast.Field) and s.chain[0] == join.alias), None)
    if base_side is None or join_side is None:
        return None
    key_name = str(join_side.chain[1])

    subquery = join.table
    if (
        subquery.group_by is None
        or len(subquery.group_by) != 1
        or subquery.having is not None
        or subquery.limit is not None
        or subquery.order_by
        or subquery.distinct
        or subquery.settings is not None
        or subquery.window_exprs
        or subquery.select_from is None
    ):
        return None
    group_field = subquery.group_by[0]
    if isinstance(group_field, ast.Alias):
        group_field = group_field.expr
    if not isinstance(group_field, ast.Field) or str(group_field.chain[-1]) != key_name:
        return None
    if not _table_is_federated(subquery.select_from):
        return None

    columns: list[tuple[str, _ColumnKind]] = []
    key_seen = False
    for col in subquery.select:
        if not isinstance(col, ast.Alias):
            return None
        if col.alias == key_name:
            key_seen = True
            continue
        kind = _classify_column(col.expr)
        if kind is None:
            return None
        columns.append((col.alias, kind))
    if not key_seen or not columns:
        return None

    return _Candidate(
        prev=prev,
        join=join,
        alias=join.alias,
        subquery=subquery,
        key_name=key_name,
        base_key_chain=tuple(base_side.chain),
        columns=columns,
    )


def _pad_expr(kind: str) -> ast.Expr:
    if kind == "array":
        return ast.Array(exprs=[])
    return ast.Constant(value=None)


def _merge_in_select(
    node: ast.SelectQuery,
    context: HogQLContext,
    dialect: HogQLDialect,
    resolver_factory: ResolverFactory | None,
) -> bool:
    if node.select_from is None or node.select_from.next_join is None or node.type is None:
        return False
    # A pre-existing table under the reserved alias would collide with the merged join
    # during resolution, so leave such a select untouched.
    if MERGED_ALIAS in node.type.tables:
        return False
    base_alias = node.select_from.alias
    if base_alias is None and isinstance(node.select_from.table, ast.Field):
        base_alias = str(node.select_from.table.chain[0])
    if base_alias is None:
        return False

    candidates: list[_Candidate] = []
    prev = node.select_from
    join = prev.next_join
    while join is not None:
        candidate = _candidate_for_join(prev, join, base_alias)
        if candidate is not None:
            candidates.append(candidate)
        prev = join
        join = join.next_join

    if len(candidates) < 2:
        return False
    # All merged joins must share one base key and one key column name, and no column
    # name may repeat across them, because the merged subquery exposes them side by side.
    if len({c.base_key_chain for c in candidates}) != 1 or len({c.key_name for c in candidates}) != 1:
        return False
    all_columns = [col for c in candidates for col in c.columns]
    if len({name for name, _ in all_columns}) != len(all_columns):
        return False

    branches: list[ast.SelectQuery] = []
    for candidate in candidates:
        own = {name for name, _ in candidate.columns}
        select: list[ast.Expr] = [ast.Alias(alias=MERGED_KEY, expr=ast.Field(chain=[candidate.key_name]))]
        for name, kind in all_columns:
            expr = ast.Field(chain=[name]) if name in own else _pad_expr(kind)
            select.append(ast.Alias(alias=name, expr=expr))
        branches.append(
            ast.SelectQuery(
                select=select,
                select_from=ast.JoinExpr(table=clone_expr(candidate.subquery, clear_types=True)),
            )
        )

    # Qualify through an alias: a bare `count` column reference inside max() would be
    # ambiguous with the count() function for both resolvers.
    outer_select: list[ast.Expr] = [
        ast.Alias(alias=MERGED_KEY, expr=ast.Field(chain=["__branches", MERGED_KEY])),
    ]
    for name, kind in all_columns:
        merged: ast.Expr = ast.Call(name="max", args=[ast.Field(chain=["__branches", name])])
        if kind == "count":
            merged = ast.Call(name="coalesce", args=[merged, ast.Constant(value=0)])
        outer_select.append(ast.Alias(alias=name, expr=merged))
    merged_subquery = ast.SelectQuery(
        select=outer_select,
        select_from=ast.JoinExpr(
            alias="__branches",
            table=ast.SelectSetQuery.create_from_queries(branches, "UNION ALL"),
        ),
        group_by=[ast.Field(chain=["__branches", MERGED_KEY])],
    )

    merged_join = ast.JoinExpr(
        alias=MERGED_ALIAS,
        table=merged_subquery,
        join_type="LEFT JOIN",
        constraint=ast.JoinConstraint(
            constraint_type="ON",
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=list(candidates[0].base_key_chain)),
                right=ast.Field(chain=[MERGED_ALIAS, MERGED_KEY]),
            ),
        ),
    )
    # Resolve only the new join against the select's scope (the same pattern lazy-table
    # resolution uses per join). A whole-tree re-resolve is off the table: it would
    # recreate LazyJoinTypes for sibling lazy joins (e.g. warehouse tables) that
    # resolve_lazy_tables has already run for and won't expand again.
    merged_join = resolve_types(merged_join, context, dialect, [node.type], resolver_factory=resolver_factory)
    if not isinstance(merged_join.type, ast.SelectQueryAliasType):
        return False

    _splice_merged_join(node.select_from, candidates, merged_join)

    node.type.tables[MERGED_ALIAS] = merged_join.type
    for candidate in candidates:
        node.type.tables.pop(candidate.alias, None)

    _AliasRewriter({c.alias for c in candidates}, merged_type=merged_join.type, skip=merged_subquery).visit(node)
    return True


def _splice_merged_join(select_from: ast.JoinExpr, candidates: list[_Candidate], merged_join: ast.JoinExpr) -> None:
    merged_joins = {id(c.join) for c in candidates}
    ptr = select_from
    while ptr.next_join is not None:
        if id(ptr.next_join) in merged_joins:
            ptr.next_join = ptr.next_join.next_join
        else:
            ptr = ptr.next_join
    merged_join.next_join = select_from.next_join
    select_from.next_join = merged_join


class _AliasRewriter(TraversingVisitor):
    """Repoint outer references from the merged joins' aliases to the combined alias."""

    def __init__(self, aliases: set[str], merged_type: ast.SelectQueryAliasType, skip: ast.SelectQuery) -> None:
        super().__init__()
        self.aliases = aliases
        self.merged_type = merged_type
        self.skip = skip

    def visit_select_query(self, node: ast.SelectQuery):
        if node is self.skip:
            return
        super().visit_select_query(node)

    def _repoint(self, node: ast.Field, column: str) -> None:
        node.chain = [MERGED_ALIAS, column]
        node.type = ast.FieldType(name=column, table_type=self.merged_type)

    def visit_field(self, node: ast.Field):
        # Lazy-table resolution retypes fields without rewriting their chains (e.g.
        # `accounts.tags.names` typed onto the `accounts__tags` join), so a chain check
        # misses them, so resolve the owning join through the field's type first. Nested
        # JSON key accesses arrive as PropertyTypes carrying the materialized column name.
        field_type = node.type
        if isinstance(field_type, ast.PropertyType):
            inner = field_type.field_type
            table_type = inner.table_type
            if isinstance(table_type, ast.SelectQueryAliasType) and table_type.alias in self.aliases:
                materialized = field_type.joined_subquery_field_name or "___".join(
                    [inner.name, *(str(x) for x in field_type.chain)]
                )
                self._repoint(node, materialized)
                return
        if isinstance(field_type, ast.FieldType):
            table_type = field_type.table_type
            if isinstance(table_type, ast.SelectQueryAliasType) and table_type.alias in self.aliases:
                self._repoint(node, field_type.name)
                return
        if len(node.chain) >= 2 and node.chain[0] in self.aliases:
            self._repoint(node, str(node.chain[1]))
