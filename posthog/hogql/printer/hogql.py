from typing import cast

from posthog.hogql import ast
from posthog.hogql.printer.base import BasePrinter


class HogQLPrinter(BasePrinter):
    """Prints a HogQL AST back out as HogQL text.

    This is the ``dialect="hogql"`` output path — it preserves HogQL-native
    syntax (nullish access, cohort ops, placeholder arguments) rather than
    lowering the tree to a target SQL dialect.
    """

    def _render_aggregation_name(self, node: ast.Call, func_meta) -> str:
        return node.name

    def _ensure_team_id_where_clause(
        self,
        table_type: ast.TableType | ast.LazyTableType,
        node_type: ast.TableOrSelectType,
    ):
        return

    def _print_table_ref(self, table_type: ast.TableType | ast.LazyTableType, node: ast.JoinExpr) -> str:
        return table_type.table.to_printed_hogql()

    def _tuple_access_separator(self, nullish: bool) -> str:
        return "?." if nullish else "."

    def _array_access_prefix(self, nullish: bool) -> str:
        return "?." if nullish else ""

    def _render_cohort_compare_op(self, op: ast.CompareOperationOp, left: str, right: str) -> str | None:
        if op == ast.CompareOperationOp.InCohort:
            return f"{left} IN COHORT {right}"
        if op == ast.CompareOperationOp.NotInCohort:
            return f"{left} NOT IN COHORT {right}"
        return None

    def _render_lazy_table_join_expr(self, node: ast.JoinExpr) -> str:
        table_type = cast(ast.LazyTableType, node.type)
        return self._print_identifier(table_type.table.to_printed_hogql())

    def _render_untyped_join_expr(self, node: ast.JoinExpr) -> list[str]:
        parts = [self.visit(node.table)]
        if node.alias is not None:
            parts.append(f"AS {self._print_identifier(node.alias)}")
        return parts

    def _expands_placeholder_macros(self) -> bool:
        return False

    def _render_connection_supported_function(self, node: ast.Call) -> str | None:
        if node.name.lower() in self._get_connection_supported_functions():
            return f"{node.name}({', '.join([self.visit(arg) for arg in node.args])})"
        return None
