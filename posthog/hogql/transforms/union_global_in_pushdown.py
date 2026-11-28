"""Move a GLOBAL IN filter on a UNION ALL of events_json reads into each branch of the union.

ClickHouse pushes a filter on a UNION ALL down into each branch. When the filter is a GLOBAL IN and the branches read
the sharded events_json table, a query that starts on a node outside the shard cluster returns the rows of the last
branch only, with no error. The same GLOBAL IN written in each branch returns the rows of every branch:

    FROM (SELECT a AS x FROM events UNION ALL SELECT b AS x FROM events) WHERE x GLOBAL IN (S)
    ->
    FROM (SELECT a AS x FROM events WHERE a GLOBAL IN (S) UNION ALL SELECT b AS x FROM events WHERE b GLOBAL IN (S))

The two forms keep the same rows when no branch aggregates, deduplicates, limits or multiplies its rows, so the
transform declines a branch that does one of these. A FROM that reads a CTE gets a copy of the CTE body, so other
reads of the CTE do not change.
"""

import dataclasses
from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import (
    contains_row_multiplying_function,
    is_nondeterministic_function,
    top_level_conjuncts,
)
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.dataclasses import frozen

_GLOBAL_IN_OPS = frozenset({ast.CompareOperationOp.GlobalIn, ast.CompareOperationOp.GlobalNotIn})

_UnionTableType = ast.CTETableType | ast.CTETableAliasType | ast.SelectQueryAliasType | ast.SelectSetQueryType


@frozen
class _Pushdown:
    union: ast.SelectSetQuery
    union_type: _UnionTableType
    alias: str | None
    moved: list[ast.CompareOperation]
    kept: list[ast.Expr]


def push_global_in_into_union_branches(node: _T_AST, context: HogQLContext) -> _T_AST | None:
    """Returns None when no SELECT qualifies. Otherwise it emits untyped nodes. The caller runs type resolution again."""
    planner = _Planner()
    planner.visit(node)
    if planner.blocks_rewrite or not planner.pushdowns or not context.uses_new_events_schema():
        return None
    return cast(_T_AST, _Rewriter(planner.pushdowns).visit(node))


def _union_all_branches(query: ast.SelectQuery | ast.SelectSetQuery) -> list[ast.SelectQuery] | None:
    if isinstance(query, ast.SelectQuery):
        return [query]
    if query.limit is not None or query.offset is not None:
        return None
    if any(node.set_operator != "UNION ALL" for node in query.subsequent_select_queries):
        return None
    branches: list[ast.SelectQuery] = []
    for sub_query in query.select_queries():
        sub_branches = _union_all_branches(sub_query)
        if sub_branches is None:
            return None
        branches.extend(sub_branches)
    return branches


def _column_name(expr: ast.Expr) -> str | None:
    if isinstance(expr, ast.Alias):
        return expr.alias
    if isinstance(expr, ast.Field) and isinstance(expr.chain[-1], str):
        return expr.chain[-1]
    return None


def _unaliased(expr: ast.Expr) -> ast.Expr:
    return expr.expr if isinstance(expr, ast.Alias) else expr


class _UnsafeColumnFinder(TraversingVisitor):
    """Finds an aggregate, a window function or a nondeterministic call. A copy of one in WHERE changes the result."""

    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_call(self, node: ast.Call) -> None:
        if find_hogql_aggregation(node.name) is not None or is_nondeterministic_function(node.name):
            self.found = True
            return
        super().visit_call(node)

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.found = True


def _is_plain_branch(branch: ast.SelectQuery) -> bool:
    if (
        branch.distinct
        or branch.group_by
        or branch.having
        or branch.qualify
        or branch.limit
        or branch.limit_by
        or branch.offset
        or branch.window_exprs
        or branch.array_join_op
        or branch.array_join_list
    ):
        return False
    for expr in branch.select:
        finder = _UnsafeColumnFinder()
        finder.visit(expr)
        if finder.found or contains_row_multiplying_function(expr):
            return False
    return True


class _EventsTableFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_table_type(self, node: ast.TableType) -> None:
        if isinstance(node.table, EventsTable):
            self.found = True


def _reads_events(query: ast.SelectSetQuery) -> bool:
    finder = _EventsTableFinder()
    finder.visit(query)
    return finder.found


def _union_column(field_type: ast.Type | None, union_type: _UnionTableType) -> str | None:
    while isinstance(field_type, ast.FieldAliasType):
        field_type = field_type.type
    if isinstance(field_type, ast.FieldType) and field_type.table_type is union_type:
        return field_type.name
    return None


class _UnionColumnsOnly(TraversingVisitor):
    """Checks that every field of an expression is a column of the union, so the expression can move into a branch."""

    def __init__(self, union_type: _UnionTableType, columns: set[str]) -> None:
        super().__init__()
        self.union_type = union_type
        self.columns = columns
        self.reads_union = False
        self.reads_other = False

    def visit_field(self, node: ast.Field) -> None:
        if _union_column(node.type, self.union_type) in self.columns:
            self.reads_union = True
        else:
            self.reads_other = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.reads_other = True

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.reads_other = True


class _Planner(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.pushdowns: dict[int, _Pushdown] = {}
        self.cte_bodies: dict[int, ast.CTE] = {}
        self.blocks_rewrite = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # The caller resolves the whole tree again. That drops the isolated scope of expanded expression fields such as
        # `events.person_id`, so their unqualified inner fields become ambiguous in a SELECT that joins two tables.
        if node.select_from is not None and node.select_from.next_join is not None:
            self.blocks_rewrite = True
        for cte in (node.ctes or {}).values():
            if cte.expr.type is not None:
                self.cte_bodies[id(cte.expr.type)] = cte
        super().visit_select_query(node)
        pushdown = self._plan(node)
        if pushdown is not None:
            self.pushdowns[id(node)] = pushdown

    def visit_field(self, node: ast.Field) -> None:
        pass

    def _union_source(self, join: ast.JoinExpr) -> tuple[ast.SelectSetQuery, str | None] | None:
        if isinstance(join.table, ast.SelectSetQuery):
            return join.table, join.alias
        table_type = join.type
        if isinstance(table_type, ast.CTETableAliasType):
            alias, table_type = table_type.alias, table_type.cte_table_type
        elif isinstance(table_type, ast.CTETableType):
            alias = table_type.name
        else:
            return None
        cte = self.cte_bodies.get(id(table_type.select_query_type))
        if (
            cte is None
            or not isinstance(cte.expr, ast.SelectSetQuery)
            or cte.recursive
            or cte.materialized
            or cte.columns
            or cte.using_key
        ):
            return None
        return cte.expr, alias

    def _plan(self, node: ast.SelectQuery) -> _Pushdown | None:
        join = node.select_from
        if node.where is None or node.array_join_op or join is None or join.next_join is not None or join.type is None:
            return None
        source = self._union_source(join)
        if source is None:
            return None
        union, alias = source
        branches = _union_all_branches(union)
        if branches is None or not all(_is_plain_branch(branch) for branch in branches):
            return None
        names = [_column_name(expr) for expr in branches[0].select]
        columns = {name for name in names if name is not None}
        if len(columns) != len(names) or any(len(branch.select) != len(names) for branch in branches):
            return None
        if not _reads_events(union):
            return None

        union_type = cast(_UnionTableType, join.type)
        moved: list[ast.CompareOperation] = []
        kept: list[ast.Expr] = []
        for conjunct in top_level_conjuncts(node.where):
            if isinstance(conjunct, ast.CompareOperation) and conjunct.op in _GLOBAL_IN_OPS:
                scan = _UnionColumnsOnly(union_type, columns)
                scan.visit(conjunct.left)
                if scan.reads_union and not scan.reads_other:
                    moved.append(conjunct)
                    continue
            kept.append(conjunct)
        if not moved:
            return None
        return _Pushdown(union=union, union_type=union_type, alias=alias, moved=moved, kept=kept)


class _BranchColumnInliner(CloningVisitor):
    """Clones an expression on union columns into the same expression on the select expressions of one branch."""

    def __init__(self, union_type: _UnionTableType, columns: dict[str, ast.Expr]) -> None:
        super().__init__(clear_types=True)
        self.union_type = union_type
        self.columns = columns

    def visit_field(self, node: ast.Field) -> ast.Expr:
        name = _union_column(node.type, self.union_type)
        if name is not None:
            return clone_expr(self.columns[name], clear_types=True)
        return super().visit_field(node)


def _and(exprs: list[ast.Expr]) -> ast.Expr | None:
    if not exprs:
        return None
    return exprs[0] if len(exprs) == 1 else ast.And(exprs=exprs)


class _Rewriter(CloningVisitor):
    def __init__(self, pushdowns: dict[int, _Pushdown]) -> None:
        super().__init__(clear_types=True)
        self.pushdowns = pushdowns

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        pushdown = self.pushdowns.get(id(node))
        if pushdown is None:
            return super().visit_select_query(node)
        query = super().visit_select_query(dataclasses.replace(node, where=None))
        query.where = _and([self.visit(conjunct) for conjunct in pushdown.kept])
        query.select_from = ast.JoinExpr(table=self._filtered_union(pushdown), alias=pushdown.alias)
        return query

    def _filtered_union(self, pushdown: _Pushdown) -> ast.SelectSetQuery:
        union = cast(ast.SelectSetQuery, self.visit(pushdown.union))
        original_branches = _union_all_branches(pushdown.union)
        branches = _union_all_branches(union)
        assert original_branches is not None and branches is not None
        names = [cast(str, _column_name(expr)) for expr in original_branches[0].select]
        for original, branch in zip(original_branches, branches, strict=True):
            inliner = _BranchColumnInliner(
                pushdown.union_type,
                {name: _unaliased(expr) for name, expr in zip(names, original.select, strict=True)},
            )
            filters: list[ast.Expr] = [
                ast.CompareOperation(
                    op=conjunct.op, left=inliner.visit(conjunct.left), right=self.visit(conjunct.right)
                )
                for conjunct in pushdown.moved
            ]
            branch.where = _and([branch.where, *filters] if branch.where is not None else filters)
        return union
