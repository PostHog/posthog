from collections import defaultdict
from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import TraversingVisitor

# SelectQuery fields that can read a column of a subquery or CTE in FROM. A column that only a
# skipped clause reads is never demanded, so the pruner drops it and the query fails.
COLUMN_READING_CLAUSES: tuple[str, ...] = (
    "array_join_list",
    "window_exprs",
    "where",
    "prewhere",
    "having",
    "qualify",
    "group_by",
    "order_by",
    "interpolate",
    "limit_by",
    "limit",
    "offset",
)

# Set operators that keep every row of every branch. The others compare whole rows, so a column
# pruned from the branches changes which rows match.
ROW_PRESERVING_SET_OPERATORS: frozenset[ast.SetOperator] = frozenset({"UNION ALL", "UNION ALL BY NAME"})


def _positional_refs(node: ast.SelectQuery) -> list[ast.Constant | ast.PositionalRef]:
    # ORDER BY, GROUP BY and LIMIT BY read a bare integer (and `#n`) as a 1-based position in the
    # select list, so dropping a column before it makes the position point at a different column.
    exprs: list[ast.Expr] = [order.expr for order in node.order_by or []]
    for expr in node.group_by or []:
        exprs.extend(expr.exprs if isinstance(expr, ast.GroupingSet) else [expr])
    if node.limit_by:
        exprs.extend(node.limit_by.exprs)
    return [
        expr
        for expr in exprs
        if isinstance(expr, ast.PositionalRef)
        or (isinstance(expr, ast.Constant) and isinstance(expr.value, int) and not isinstance(expr.value, bool))
    ]


def _position(ref: ast.Constant | ast.PositionalRef) -> int:
    return ref.index if isinstance(ref, ast.PositionalRef) else ref.value


def _set_operation_parts(node: ast.SelectSetQuery) -> tuple[list[ast.SetOperator], list[ast.SelectQuery]]:
    """Return every set operator and every SELECT leaf of a set operation, nested ones included."""
    operators: list[ast.SetOperator] = []
    leaves: list[ast.SelectQuery] = []
    for set_node in node.subsequent_select_queries:
        operators.append(set_node.set_operator)
    for query in node.select_queries():
        if isinstance(query, ast.SelectSetQuery):
            nested_operators, nested_leaves = _set_operation_parts(query)
            operators.extend(nested_operators)
            leaves.extend(nested_leaves)
        else:
            leaves.append(query)
    return operators, leaves


class ProjectionPushdownOptimizer(TraversingVisitor):
    """
    Top-down projection pushdown optimizer that prunes unused asterisk-expanded columns from subqueries.

    Algorithm Overview:
    ──────────────────
    This optimizer makes two top-down passes through the query tree: the first only collects
    demands, the second prunes with the complete demand set. A CTE can be consumed by nodes
    visited after it — notably sibling UNION branches — so pruning must wait for the full walk.

    Each pass runs these phases per query:

    Phase 1 - Register: Map subquery types to AST nodes for demand tracking
    Phase 2 - Collect: Gather column demands from every clause in COLUMN_READING_CLAUSES
    Phase 3 - Propagate: For demanded columns, visit their source to propagate to child queries
    Phase 4 - Recurse: Visit child subqueries (repeat phases 1-4)
    Phase 5 - Prune: Remove unreferenced asterisk columns from this query (second pass only)

    A column is only pruned when nothing in the query depends on it (see `_kept_columns`). The
    query itself depends on a column that ORDER BY, GROUP BY or LIMIT BY names by position, and on
    every column when DISTINCT or GROUP BY ALL compares whole rows. The branches of a set operation
    line up by position, so they are pruned only when every branch drops the same columns.
    """

    def __init__(self):
        super().__init__()
        self.demands: dict[int, set[str]] = defaultdict(set)
        self.subquery_map: dict[int, ast.SelectQuery | ast.SelectSetQuery] = {}
        # True during the first pass; gates pruning to the second (see class docstring)
        self.collecting: bool = False

    def optimize(self, node: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery | ast.SelectSetQuery:
        self.collecting = True
        self.visit(node)
        self.collecting = False
        return cast(ast.SelectQuery | ast.SelectSetQuery, self.visit(node))

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        # Phase 1: Register subqueries and CTEs for demand tracking
        if node.ctes:
            self._register_ctes(node.ctes)
        if node.select_from:
            self._register_subqueries(node.select_from)

        # Phase 2: Collect column demands from query clauses
        for expr in node.select:
            if not self._is_from_asterisk(expr):
                self.visit(expr)

        for clause in COLUMN_READING_CLAUSES:
            self._visit_clause(getattr(node, clause))

        if node.select_from:
            self._collect_join_constraint_column_demands(node.select_from)

        # Phase 3: Propagate parent demands down to child subqueries
        self._propagate_demands_to_children(node)

        # Phase 4: Recursively visit and optimize child subqueries and CTEs
        if node.ctes:
            self._visit_ctes(node.ctes)
        if node.select_from:
            self.visit(node.select_from)

        # Phase 5: Prune unreferenced asterisk columns from this query and CTEs (second pass only)
        if not self.collecting:
            self._prune_columns(node)
            if node.ctes:
                self._prune_cte_columns(node.ctes)

        return node

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.SelectSetQuery:
        """
        Handle UNION/INTERSECT/EXCEPT queries.

        All branches must have identical column structure, so we:
        1. Propagate parent demands to all branches uniformly
        2. Visit each branch to apply pruning
        """
        # Propagate parent demands to all branches uniformly
        self._propagate_demands_to_union_branches(node)

        # Visit each branch
        self.visit(node.initial_select_query)
        for set_node in node.subsequent_select_queries:
            self.visit(set_node.select_query)

        return node

    def _is_from_asterisk(self, expr: ast.Expr) -> bool:
        """Check if an expression was expanded from asterisk"""
        if isinstance(expr, ast.Alias):
            expr = expr.expr  # whoops - we want to take the Field from the Alias
        if isinstance(expr, ast.Field):
            return expr.from_asterisk
        return False

    def _visit_clause(self, clause: object) -> None:
        if isinstance(clause, dict):
            clause = list(clause.values())
        for item in clause if isinstance(clause, list) else [clause]:
            if isinstance(item, ast.AST):
                self.visit(item)

    def _kept_columns(self, node: ast.SelectQuery, demanded: set[str]) -> list[int] | None:
        """Return the indexes of the select columns that pruning keeps, in select order.

        Return None when the whole select list must stay: its columns decide which rows exist
        (DISTINCT, GROUP BY ALL), a position is outside the select list (a negative position
        counts from the end), or no column would remain.
        """
        if node.distinct or node.group_by_mode == "all":
            return None
        positional: set[int] = set()
        for ref in _positional_refs(node):
            position = _position(ref)
            if not 1 <= position <= len(node.select):
                return None
            positional.add(position - 1)

        kept: list[int] = []
        for index, expr in enumerate(node.select):
            col_name = self._get_column_name(expr)
            if not self._is_from_asterisk(expr) or index in positional or (col_name and col_name in demanded):
                kept.append(index)
        return kept or None

    def _propagate_demands_to_children(self, node: ast.SelectQuery) -> None:
        """
        Propagate parent demands to child subqueries.

        When a parent query demands a column from us, we need to visit that column's
        source expression to propagate the demand down to our child subqueries.

        If there are no parent demands but we have asterisk columns,
        this query defines the output. Visit all asterisk columns to preserve them.
        """
        demanded_from_this = self.demands.get(id(node))
        kept = self._kept_columns(node, demanded_from_this) if demanded_from_this else None
        if kept is None:
            for expr in node.select:
                if self._is_from_asterisk(expr):
                    self.visit(expr)
            return

        for index in kept:
            if self._is_from_asterisk(node.select[index]):
                self.visit(node.select[index])

    def _propagate_demands_to_union_branches(self, node: ast.SelectSetQuery) -> None:
        """
        Propagate demands from parent to all UNION/INTERSECT/EXCEPT branches.

        All branches must keep identical column structure, so they get the same demands, and
        only when every operator is a UNION ALL and every branch would drop the same columns.
        """
        demanded_from_this = self.demands.get(id(node))
        if not demanded_from_this:
            return

        # Branches that are not pruned keep every column, which is always correct.
        operators, leaves = _set_operation_parts(node)
        kept_by_leaf = [self._kept_columns(leaf, demanded_from_this) for leaf in leaves]
        if any(operator not in ROW_PRESERVING_SET_OPERATORS for operator in operators) or any(
            kept is None or kept != kept_by_leaf[0] for kept in kept_by_leaf
        ):
            self._clear_branch_demands(node)
            return

        all_queries = [node.initial_select_query] + [sn.select_query for sn in node.subsequent_select_queries]

        for query in all_queries:
            if isinstance(query, ast.SelectQuery | ast.SelectSetQuery):
                self.demands[id(query)].update(demanded_from_this)

    def _clear_branch_demands(self, node: ast.SelectSetQuery) -> None:
        # The first pass can push a partial demand set into the branches before a later consumer
        # of the same CTE adds to it. Clear it, or that stale set still prunes the branches.
        for query in node.select_queries():
            self.demands.pop(id(query), None)
            if isinstance(query, ast.SelectSetQuery):
                self._clear_branch_demands(query)

    def _register_subqueries(self, from_clause: ast.JoinExpr) -> None:
        """Register all subqueries in FROM clause before collecting demands"""
        if from_clause.type is None:
            return

        if isinstance(from_clause.table, ast.SelectQuery):
            self._register_subquery(from_clause.table, cast(ast.SelectQueryType, from_clause.type))
        elif isinstance(from_clause.table, ast.SelectSetQuery):
            self._register_union_subquery(from_clause.table, cast(ast.SelectSetQueryType, from_clause.type))

        if from_clause.next_join:
            self._register_subqueries(from_clause.next_join)

    def _register_subquery(
        self,
        subquery: ast.SelectQuery,
        type_annotation: ast.BaseTableType | ast.SelectSetQueryType | ast.SelectQueryType | ast.SelectQueryAliasType,
    ) -> None:
        """Map type to subquery node for demand tracking"""
        # Map both the type and the inner SelectQueryType if it's an alias
        self.subquery_map[id(type_annotation)] = subquery
        if isinstance(type_annotation, ast.SelectQueryAliasType) and type_annotation.select_query_type:
            self.subquery_map[id(type_annotation.select_query_type)] = subquery

    def _register_union_subquery(
        self,
        union_query: ast.SelectSetQuery,
        type_annotation: ast.BaseTableType | ast.SelectSetQueryType | ast.SelectQueryType | ast.SelectQueryAliasType,
    ) -> None:
        """Map type to union subquery node for demand tracking"""
        self.subquery_map[id(type_annotation)] = union_query

        # Also register with the inner SelectSetQueryType for both aliased and non-aliased cases
        if isinstance(type_annotation, ast.SelectQueryAliasType):
            # Aliased: register with the inner select_query_type
            if type_annotation.select_query_type:
                self.subquery_map[id(type_annotation.select_query_type)] = union_query
        elif isinstance(type_annotation, ast.SelectSetQueryType):
            # Non-aliased: the type_annotation IS the SelectSetQueryType, but we also need to
            # register with the first branch's type for field resolution
            if type_annotation.types:
                self.subquery_map[id(type_annotation.types[0])] = union_query

    def _get_subquery(self, table_type: ast.Type) -> ast.SelectQuery | ast.SelectSetQuery | None:
        """Retrieve subquery by type"""
        return self.subquery_map.get(id(table_type))

    def visit_field(self, node: ast.Field) -> ast.Field:
        """Record demand when field references subquery or CTE column"""
        field_type = node.type
        # A property read (`col.some_key`) still demands its base blob column. Its node type is a
        # PropertyType wrapping the base FieldType, so unwrap to that base — otherwise the column is
        # never recorded as demanded and gets pruned from an asterisk-expanded subquery/CTE, leaving a
        # dangling reference that later blows up property lowering.
        if isinstance(field_type, ast.PropertyType):
            field_type = field_type.field_type

        # Handle both FieldType and ExpressionFieldType
        if not isinstance(field_type, ast.FieldType | ast.ExpressionFieldType):
            return node

        table_type = field_type.table_type

        if isinstance(table_type, ast.SelectQueryType | ast.SelectQueryAliasType | ast.SelectSetQueryType):
            subquery = self._get_subquery(table_type)
            if subquery:
                self.demands[id(subquery)].add(field_type.name)
        elif isinstance(table_type, ast.CTETableType | ast.CTETableAliasType):
            # For CTE types, get the underlying SelectQueryType and demand from it
            cte_select_query_type = (
                table_type.cte_table_type.select_query_type
                if isinstance(table_type, ast.CTETableAliasType)
                else table_type.select_query_type
            )
            cte_query = self._get_subquery(cte_select_query_type)
            if cte_query:
                self.demands[id(cte_query)].add(field_type.name)

        return node

    def _collect_join_constraint_column_demands(self, from_clause: ast.JoinExpr) -> None:
        """Collect demands from JOIN constraints"""
        if from_clause.constraint and from_clause.constraint.expr:
            # Visit the constraint expression (not the JoinConstraint wrapper)
            self.visit(from_clause.constraint.expr)

        if from_clause.next_join:
            self._collect_join_constraint_column_demands(from_clause.next_join)

    def _prune_columns(self, node: ast.SelectQuery) -> None:
        """Prune asterisk-expanded columns that aren't demanded"""
        demanded = self.demands.get(id(node))
        if not demanded:
            return
        kept_indexes = self._kept_columns(node, demanded)
        if kept_indexes is None:
            return

        # Collect the names of asterisk columns we're about to drop
        kept = set(kept_indexes)
        dropped_names: set[str] = set()
        for index, expr in enumerate(node.select):
            col_name = self._get_column_name(expr)
            if index not in kept and col_name:
                dropped_names.add(col_name)

        self._renumber_positions(node, kept_indexes)
        node.select = [node.select[index] for index in kept_indexes]
        # Remove dropped asterisk columns from SelectQueryType.columns.
        # Without this, stale LazyTableType references on pruned columns
        # leak through type traversal (e.g. CTETableType → SelectQueryType.columns)
        # and cause KeyErrors in the lazy table resolver.
        if dropped_names and isinstance(node.type, ast.SelectQueryType):
            node.type.columns = {k: v for k, v in node.type.columns.items() if k not in dropped_names}

    def _renumber_positions(self, node: ast.SelectQuery, kept_indexes: list[int]) -> None:
        new_index_by_old = {old: new for new, old in enumerate(kept_indexes)}
        for ref in _positional_refs(node):
            new_position = new_index_by_old[_position(ref) - 1] + 1
            if isinstance(ref, ast.PositionalRef):
                ref.index = new_position
            else:
                ref.value = new_position

    def _get_column_name(self, expr: ast.Expr) -> str | None:
        """Extract column name from expression"""
        if isinstance(expr, ast.Field):
            return str(expr.chain[-1]) if expr.chain else None
        elif isinstance(expr, ast.Alias):
            return expr.alias
        return None

    def _register_ctes(self, ctes: dict[str, ast.CTE]) -> None:
        """Register all CTEs for demand tracking"""
        for cte in ctes.values():
            if isinstance(cte.expr, ast.SelectQuery | ast.SelectSetQuery):
                # Map the CTE's SelectQueryType to its expr for demand tracking
                if cte.expr.type:
                    self.subquery_map[id(cte.expr.type)] = cte.expr

    def _visit_ctes(self, ctes: dict[str, ast.CTE]) -> None:
        """Visit and optimize CTEs"""
        for cte in ctes.values():
            if isinstance(cte.expr, ast.SelectQuery | ast.SelectSetQuery):
                self.visit(cte.expr)

    def _prune_cte_columns(self, ctes: dict[str, ast.CTE]) -> None:
        """Prune asterisk-expanded columns from CTEs that aren't demanded"""
        for cte in ctes.values():
            if isinstance(cte.expr, ast.SelectQuery):
                self._prune_columns(cte.expr)


def pushdown_projections(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Prune unused columns from asterisk expansions in subqueries"""
    if not isinstance(node, (ast.SelectQuery, ast.SelectSetQuery)):
        return node
    optimizer = ProjectionPushdownOptimizer()
    return cast(_T_AST, optimizer.optimize(node))
