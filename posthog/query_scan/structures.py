from collections import Counter

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from posthog.query_scan.tree import iter_and_terms, strip_aliases


class _LocalCalls(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.ranks = False
        self.date_array = False

    def visit_field(self, node: ast.Field) -> None:
        pass

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        pass

    def visit_call(self, node: ast.Call) -> None:
        if node.name == "rowNumberInAllBlocks":
            self.ranks = True
        if node.name == "groupArray" and node.args:
            arg = strip_aliases(node.args[0])
            if isinstance(arg, ast.Field) and arg.chain[-1] in {"day_start", "timestamp", "date"}:
                self.date_array = True
        super().visit_call(node)

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        if node.name in {"row_number", "rank", "dense_rank"}:
            self.ranks = True
        super().visit_window_function(node)


class QueryStructures(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.ctes: dict[int, ast.CTE] = {}
        self.references: Counter[int] = Counter()
        self.cross_join_equalities = 0
        self.date_arrays_before_breakdown_limit = False

    def visit_field(self, node: ast.Field) -> None:
        pass

    def visit_cte(self, node: ast.CTE) -> None:
        if node.expr.type is not None:
            self.ctes[id(node.expr.type)] = node
        super().visit_cte(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        table_type = node.table.type if node.table is not None else None
        if isinstance(table_type, ast.CTETableAliasType):
            table_type = table_type.cte_table_type
        if isinstance(table_type, ast.CTETableType):
            self.references[id(table_type.select_query_type)] += 1
        super().visit_join_expr(node)

    @staticmethod
    def _alias(join: ast.JoinExpr) -> str | None:
        if join.alias is not None:
            return join.alias
        if isinstance(join.table, ast.Field) and len(join.table.chain) == 1:
            return str(join.table.chain[0])
        return None

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        calls = _LocalCalls()
        for expr in node.select:
            calls.visit(expr)
        breakdown_group = any(
            isinstance(expr := strip_aliases(group), ast.Field) and expr.chain[-1] == "breakdown_value"
            for group in node.group_by or []
        )
        if calls.ranks and calls.date_array and breakdown_group:
            self.date_arrays_before_breakdown_limit = True
        left_aliases: set[str] = set()
        join = node.select_from
        while join is not None:
            right_alias = self._alias(join)
            if join.join_type == "CROSS JOIN" and right_alias:
                for term in iter_and_terms(node.where):
                    if not isinstance(term, ast.CompareOperation) or term.op != ast.CompareOperationOp.Eq:
                        continue
                    left, right = strip_aliases(term.left), strip_aliases(term.right)
                    if (
                        isinstance(left, ast.Field)
                        and isinstance(right, ast.Field)
                        and len(left.chain) > 1
                        and len(right.chain) > 1
                    ):
                        if (left.chain[0] in left_aliases and right.chain[0] == right_alias) or (
                            right.chain[0] in left_aliases and left.chain[0] == right_alias
                        ):
                            self.cross_join_equalities += 1
            if right_alias:
                left_aliases.add(right_alias)
            join = join.next_join
        super().visit_select_query(node)

    def repeated_cte_expansions(self) -> int:
        return sum(
            count - 1
            for type_id, count in self.references.items()
            if count > 1 and type_id in self.ctes and self.ctes[type_id].materialized is not True
        )
