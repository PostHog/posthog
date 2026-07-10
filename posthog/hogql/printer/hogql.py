from typing import ClassVar, cast

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.printer.base import BasePrinter


class HogQLPrinter(BasePrinter):
    """Prints a HogQL AST back out as HogQL text.

    This is the ``dialect="hogql"`` output path — it preserves HogQL-native
    syntax (nullish access, cohort ops, placeholder arguments) rather than
    lowering the tree to a target SQL dialect.
    """

    DIALECT_NAME: ClassVar[HogQLDialect] = "hogql"

    def _assert_qualify_supported(self) -> None:
        # QUALIFY is valid HogQL (the grammar and resolver support it), so the canonical
        # round-trip must print it back rather than reject — otherwise any query carrying a
        # QUALIFY clause fails when `query.py` renders `self.hogql` for the response, before
        # the target dialect ever runs.
        return

    def visit_cte(self, node: ast.CTE) -> str:
        materialization_hint = (
            "" if node.materialized is None else ("MATERIALIZED " if node.materialized else "NOT MATERIALIZED ")
        )

        if node.cte_type == "subquery":
            columns_sql = (
                "" if node.columns is None else f"({', '.join(self._print_identifier(col) for col in node.columns)})"
            )
            using_key_sql = (
                ""
                if node.using_key is None
                else f" USING KEY ({', '.join(self._print_identifier(col) for col in node.using_key)})"
            )
            return f"{self._print_identifier(node.name)}{columns_sql}{using_key_sql} AS {materialization_hint}{self.visit(node.expr)}"

        return super().visit_cte(node)

    def visit_property_access(self, node: ast.PropertyAccess) -> str:
        # A lowered `properties.$x` read prints back as the HogQL property chain it came from, not the ClickHouse
        # `JSONExtractRaw(...)` form the base renderer emits — so `dialect="hogql"` stays valid, re-parseable HogQL
        # (e.g. the stored batch-export `hogql_query`). The keys join onto the blob field as chain access.
        parts = [self.visit(node.expr)]
        parts.extend(self._print_identifier(str(key)) for key in node.keys)
        return ".".join(parts)

    def visit_json_subcolumn_access(self, node: ast.JsonSubcolumnAccess) -> str:
        parts = [self.visit(node.expr)]
        if node.access_type == "sub_object" and node.keys:
            parts.append("^" + self._print_identifier(node.keys[0]))
            parts.extend(self._print_identifier(key) for key in node.keys[1:])
            return ".".join(parts)
        parts.extend(self._print_identifier(key) for key in node.keys)
        return ".".join(parts)

    def _render_aggregation_name(self, node: ast.Call, func_meta) -> str:
        return node.name

    def _ensure_team_id_where_clause(
        self,
        table_type: ast.TableType | ast.LazyTableType,
        node_type: ast.TableOrSelectType,
    ):
        return

    def _ensure_access_control_where_clause(
        self,
        table_type: ast.TableType | ast.LazyTableType,
        node_type: ast.TableOrSelectType | None,
    ) -> ast.Expr | None:
        # HogQL output never produces a real query, so no access-control guard is injected.
        return None

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
