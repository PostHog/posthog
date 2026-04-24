import re
from typing import ClassVar

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.errors import InternalHogQLError, QueryError
from posthog.hogql.printer.clickhouse import ClickHousePrinter

_SAFE_FUNCTION_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DirectClickHousePrinter(ClickHousePrinter):
    DIALECT_NAME: ClassVar[HogQLDialect] = "direct_clickhouse"

    def visit_select_query(self, node: ast.SelectQuery):
        if not self.context.enable_select_queries:
            raise InternalHogQLError("Full SELECT queries are disabled if context.enable_select_queries is False")

        return super(ClickHousePrinter, self).visit_select_query(node)

    def visit_call(self, node: ast.Call):
        if not _SAFE_FUNCTION_NAME_RE.match(node.name):
            raise QueryError(f"Unsupported function call '{node.name}': function name contains invalid characters.")

        params = [self.visit(param) for param in node.params] if node.params is not None else None
        params_part = f"({', '.join(params)})" if params is not None else ""
        args = [self.visit(arg) for arg in node.args]
        order_by_part = f" ORDER BY {', '.join(self.visit(o) for o in node.order_by)}" if node.order_by else ""
        filter_part = f" FILTER (WHERE {self.visit(node.filter_expr)})" if node.filter_expr else ""
        distinct_part = "DISTINCT " if node.distinct else ""
        return f"{node.name}{params_part}({distinct_part}{', '.join(args)}{order_by_part}){filter_part}"

    def visit_table_type(self, type: ast.TableType):
        return self._print_direct_clickhouse_table(type.table)

    def _ensure_team_id_where_clause(
        self,
        table_type: ast.TableType | ast.LazyTableType,
        node_type: ast.TableOrSelectType | None,
    ):
        return None

    def _print_table_ref(self, table_type: ast.TableType | ast.LazyTableType, node: ast.JoinExpr) -> str:
        return self._print_direct_clickhouse_table(table_type.table)

    def _get_table_name(self, table: ast.TableType) -> str:
        return self._print_direct_clickhouse_table(table.table)

    def _print_direct_clickhouse_table(self, table) -> str:
        if hasattr(table, "to_printed_direct_clickhouse"):
            return table.to_printed_direct_clickhouse(self.context)
        return table.to_printed_clickhouse(self.context)
