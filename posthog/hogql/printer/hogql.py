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
