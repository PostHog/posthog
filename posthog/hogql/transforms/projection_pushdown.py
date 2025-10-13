from collections import defaultdict

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import TraversingVisitor


class ProjectionPushdownOptimizer(TraversingVisitor):
    """
    Single-pass bottom-up optimizer that prunes unused asterisk-expanded columns from subqueries.

    The algorithm works by:
    1. Processing subqueries recursively (bottom-up via explicit visit ordering)
    2. Collecting which columns parent queries demand from each subquery
    3. Pruning asterisk-expanded columns that aren't demanded
    4. Propagating demands so nested subqueries are pruned correctly
    """

    def __init__(self):
        super().__init__()
        self.demands: dict[int, set[str]] = defaultdict(set)
        self.subquery_map: dict[int, ast.SelectQuery] = {}

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        if node.select_from:
            self.visit(node.select_from)

        # This includes JOIN constraints which are part of the FROM clause
        if node.select_from:
            self._collect_join_constraint_demands(node.select_from)

        for expr in node.select:
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
            self._prune_from_clause(node.select_from)

        return node

    def visit_join_expr(self, node: ast.JoinExpr) -> ast.JoinExpr:
        # Register subquery mapping before processing
        if isinstance(node.table, ast.SelectQuery):
            self._register_subquery(node.table, node.type)
            # Recursively process the subquery (visit its subqueries, collect demands, etc.)
            self.visit(node.table)

        if node.next_join:
            self.visit(node.next_join)

        return node

    def _collect_join_constraint_demands(self, from_clause: ast.JoinExpr) -> None:
        """Collect demands from JOIN constraints before pruning"""
        if from_clause.constraint:
            self.visit(from_clause.constraint)

        if from_clause.next_join:
            self._collect_join_constraint_demands(from_clause.next_join)

    def _prune_from_clause(self, from_clause: ast.JoinExpr) -> None:
        """Prune subqueries in the FROM clause after demands have been collected"""
        if isinstance(from_clause.table, ast.SelectQuery):
            self._prune_and_repropagate(from_clause.table)
        if from_clause.next_join:
            self._prune_from_clause(from_clause.next_join)

    def _prune_and_repropagate(self, subquery: ast.SelectQuery) -> None:
        """Prune a subquery, then recursively update demands and re-prune nested subqueries"""
        self._prune_columns(subquery)

        # After pruning, demands on nested subqueries have changed
        # We need to recalculate demands and re-prune recursively
        if subquery.select_from:
            self._recalculate_and_reprune_nested(subquery)

    def _recalculate_and_reprune_nested(self, parent_query: ast.SelectQuery) -> None:
        """After pruning parent, recalculate demands on its subqueries and re-prune them"""
        if not parent_query.select_from:
            return

        self._clear_nested_demands(parent_query.select_from)

        # Recalculate demands on nested subqueries
        for expr in parent_query.select:
            self.visit(expr)

        # Re-prune the nested subqueries with updated demands
        self._prune_from_clause(parent_query.select_from)

    def _clear_nested_demands(self, from_clause: ast.JoinExpr) -> None:
        """Clear demands for all subqueries in FROM clause"""
        if isinstance(from_clause.table, ast.SelectQuery):
            self.demands[id(from_clause.table)].clear()
        if from_clause.next_join:
            self._clear_nested_demands(from_clause.next_join)

    def visit_field(self, node: ast.Field) -> ast.Field:
        """Record demand for columns from subqueries"""
        if not isinstance(node.type, ast.FieldType):
            return node

        table_type = node.type.table_type

        # Check if this field comes from a subquery
        if isinstance(table_type, ast.SelectQueryType | ast.SelectQueryAliasType):
            subquery = self._get_subquery(table_type)
            if subquery:
                self.demands[id(subquery)].add(node.type.name)

        return node

    def _register_subquery(self, subquery: ast.SelectQuery, type_annotation: ast.Type | None) -> None:
        if not type_annotation:
            return

        # Map both the type and the inner SelectQueryType if it's an alias
        self.subquery_map[id(type_annotation)] = subquery
        if isinstance(type_annotation, ast.SelectQueryAliasType) and type_annotation.select_query_type:
            self.subquery_map[id(type_annotation.select_query_type)] = subquery

    def _get_subquery(self, table_type: ast.Type) -> ast.SelectQuery | None:
        return self.subquery_map.get(id(table_type))

    def _prune_columns(self, node: ast.SelectQuery) -> None:
        """Prune asterisk-expanded columns that aren't demanded"""
        demanded = self.demands.get(id(node))

        if demanded is None:
            return

        pruned_select = []
        for expr in node.select:
            is_from_asterisk = isinstance(expr, ast.Field | ast.Alias) and expr.from_asterisk

            if not is_from_asterisk:
                # Keep explicitly asked for columns
                pruned_select.append(expr)
            else:
                # Keep demanded asterisk columns
                col_name = self._get_column_name(expr)
                if col_name and col_name in demanded:
                    pruned_select.append(expr)

        if pruned_select:
            node.select = pruned_select

    def _get_column_name(self, expr: ast.Expr) -> str | None:
        if isinstance(expr, ast.Field):
            return str(expr.chain[-1]) if expr.chain else None
        elif isinstance(expr, ast.Alias):
            return expr.alias
        return None

    def visit(self, node: ast.AST | None):
        return super().visit(node)


def pushdown_projections(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Prune unused columns from asterisk expansions in subqueries"""
    optimizer = ProjectionPushdownOptimizer()
    return optimizer.visit(node)
