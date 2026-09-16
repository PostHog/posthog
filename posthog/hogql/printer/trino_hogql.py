from posthog.hogql import ast
from posthog.hogql.printer.hogql import HogQLPrinter


class TrinoHogQLPrinter(HogQLPrinter):
    def visit_call(self, node: ast.Call) -> str:
        # Diagnostics and inferred names must accept Trino syntax; the Trino compiler validates the calls.
        params = f"({', '.join(self.visit(param) for param in node.params)})" if node.params is not None else ""
        order_by = f" ORDER BY {', '.join(self.visit(expr) for expr in node.order_by)}" if node.order_by else ""
        args_body = f"{'DISTINCT ' if node.distinct else ''}{', '.join(self.visit(arg) for arg in node.args)}{order_by}"
        args = (
            ""
            if node.within_group is not None and not node.args and not node.distinct and not node.order_by
            else f"({args_body})"
        )
        within_group = (
            f" WITHIN GROUP (ORDER BY {', '.join(self.visit(expr) for expr in node.within_group)})"
            if node.within_group
            else ""
        )
        filter_part = f" FILTER (WHERE {self.visit(node.filter_expr)})" if node.filter_expr else ""
        return f"{node.name}{params}{args}{within_group}{filter_part}"
