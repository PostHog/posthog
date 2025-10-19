from collections import defaultdict
from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import TraversingVisitor


class ProjectionPushdownOptimizer(TraversingVisitor):
    """
    Top-down projection pushdown optimizer that prunes unused asterisk-expanded columns from subqueries.

    Algorithm Overview:
    ──────────────────
    This optimizer works in a single top-down pass through the query tree:

    Phase 1 - Register: Map subquery types to AST nodes for demand tracking
    Phase 2 - Collect: Gather column demands from WHERE/GROUP BY/ORDER BY/etc
    Phase 3 - Propagate: For demanded columns, visit their source to propagate to child queries
    Phase 4 - Recurse: Visit child subqueries (repeat phases 1-4)
    Phase 5 - Prune: Remove unreferenced asterisk columns from this query
    """

    def __init__(self):
        super().__init__()
        self.demands: dict[int, set[str]] = defaultdict(set)
        self.subquery_map: dict[int, ast.SelectQuery] = {}

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        # Phase 1: Register subqueries for demand tracking
        if node.select_from:
            self._register_subqueries(node.select_from)

        # Phase 2: Collect column demands from query clauses
        # Skip asterisk-expanded SELECT columns - their demands flow from parent queries
        for expr in node.select:
            if not self._is_from_asterisk(expr):
                self.visit(expr)

        if node.where:
            self.visit(node.where)
        if node.prewhere:
            self.visit(node.prewhere)
        if node.group_by:
            for expr in node.group_by:
                self.visit(expr)
        if node.having:
            self.visit(node.having)
        if node.order_by:
            for expr in node.order_by:
                self.visit(expr)
        if node.limit:
            self.visit(node.limit)
        if node.offset:
            self.visit(node.offset)

        if node.select_from:
            self._collect_join_constraint_column_demands(node.select_from)

        # Phase 3: Propagate parent demands down to child subqueries
        self._propagate_demands_to_children(node)

        # Phase 4: Recursively visit and optimize child subqueries
        if node.select_from:
            self.visit(node.select_from)

        # Phase 5: Prune unreferenced asterisk columns from this query
        self._prune_columns(node)

        return node

    def _is_from_asterisk(self, expr: ast.Expr) -> bool:
        """Check if an expression was expanded from asterisk"""
        return isinstance(expr, ast.Field | ast.Alias) and getattr(expr, "from_asterisk", False)

    def _propagate_demands_to_children(self, node: ast.SelectQuery) -> None:
        """
        Propagate parent demands to child subqueries.

        When a parent query demands a column from us, we need to visit that column's
        source expression to propagate the demand down to our child subqueries.
        """
        demanded_from_this = self.demands.get(id(node))
        if not demanded_from_this:
            return

        for col_name in demanded_from_this:
            for expr in node.select:
                if self._get_column_name(expr) == col_name:
                    self.visit(expr)
                    break

    def _register_subqueries(self, from_clause: ast.JoinExpr) -> None:
        """Register all subqueries in FROM clause before collecting demands"""
        if isinstance(from_clause.table, ast.SelectQuery):
            self._register_subquery(from_clause.table, from_clause.type)

        if from_clause.next_join:
            self._register_subqueries(from_clause.next_join)

    def _register_subquery(self, subquery: ast.SelectQuery, type_annotation: ast.Type | None) -> None:
        """Map type to subquery node for demand tracking"""
        if not type_annotation:
            return

        # Map both the type and the inner SelectQueryType if it's an alias
        self.subquery_map[id(type_annotation)] = subquery
        if isinstance(type_annotation, ast.SelectQueryAliasType) and type_annotation.select_query_type:
            self.subquery_map[id(type_annotation.select_query_type)] = subquery

    def _get_subquery(self, table_type: ast.Type) -> ast.SelectQuery | None:
        """Retrieve subquery by type"""
        return self.subquery_map.get(id(table_type))

    def visit_field(self, node: ast.Field) -> ast.Field:
        """Record demand when field references subquery column"""
        if not isinstance(node.type, ast.FieldType):
            return node

        table_type = node.type.table_type

        if isinstance(table_type, ast.SelectQueryType | ast.SelectQueryAliasType):
            subquery = self._get_subquery(table_type)
            if subquery:
                self.demands[id(subquery)].add(node.type.name)

        return node

    def _collect_join_constraint_column_demands(self, from_clause: ast.JoinExpr) -> None:
        """Collect demands from JOIN constraints"""
        if from_clause.constraint:
            self.visit(from_clause.constraint)

        if from_clause.next_join:
            self._collect_join_constraint_column_demands(from_clause.next_join)

    def _prune_columns(self, node: ast.SelectQuery) -> None:
        """Prune asterisk-expanded columns that aren't demanded"""
        demanded = self.demands.get(id(node))
        if not demanded:
            return

        pruned_select = []
        for expr in node.select:
            if not self._is_from_asterisk(expr):
                # Keep explicitly written columns
                pruned_select.append(expr)
            else:
                # Keep demanded asterisk columns
                col_name = self._get_column_name(expr)
                if col_name and col_name in demanded:
                    pruned_select.append(expr)

        if pruned_select:
            node.select = pruned_select

    def _get_column_name(self, expr: ast.Expr) -> str | None:
        """Extract column name from expression"""
        if isinstance(expr, ast.Field):
            return str(expr.chain[-1]) if expr.chain else None
        elif isinstance(expr, ast.Alias):
            return expr.alias
        return None


def pushdown_projections(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Prune unused columns from asterisk expansions in subqueries"""
    optimizer = ProjectionPushdownOptimizer()
    return cast(_T_AST, optimizer.visit(node))
