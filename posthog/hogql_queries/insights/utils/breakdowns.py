from posthog.schema import BreakdownFilter

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor


class _AliasStripper(CloningVisitor):
    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)


def strip_user_aliases(expr: ast.Expr) -> ast.Expr:
    # User-supplied `AS <name>` on a breakdown is display-only; leaving aliases in the
    # SQL AST risks colliding with system aliases or rendering invalid SQL in WHERE.
    # Strip recursively to cover nested (`x AS a AS b`) and inner-position
    # (`concat(x AS a, y)`) variants.
    return _AliasStripper().visit(expr)


def has_single_breakdown(breakdown_filter: BreakdownFilter | None) -> bool:
    """Return whether the single-field `breakdown` representation is populated."""
    return breakdown_filter is not None and breakdown_filter.breakdown is not None


def has_multi_breakdown(breakdown_filter: BreakdownFilter | None) -> bool:
    """Return whether the multi-field `breakdowns` representation is populated."""
    return (
        breakdown_filter is not None
        and breakdown_filter.breakdowns is not None
        and len(breakdown_filter.breakdowns) > 0
    )


def has_breakdown_filter(breakdown_filter: BreakdownFilter | None) -> bool:
    """Return whether a breakdown is configured via either supported representation."""
    return has_single_breakdown(breakdown_filter) or has_multi_breakdown(breakdown_filter)
