from posthog.schema import BreakdownFilter

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor

BREAKDOWN_OTHER_STRING_LABEL = "$$_posthog_breakdown_other_$$"
BREAKDOWN_NULL_STRING_LABEL = "$$_posthog_breakdown_null_$$"
BREAKDOWN_OTHER_DISPLAY = "Other (i.e. all remaining values)"
BREAKDOWN_NULL_DISPLAY = "None (i.e. no value)"
BREAKDOWN_NUMERIC_ALL_VALUES_PLACEHOLDER = '["",""]'

ALL_USERS_COHORT_ID = 0
# Keep in sync with NOT_IN_COHORT_ID in frontend/src/scenes/insights/utils.tsx
NOT_IN_COHORT_ID = 2**52


def humanize_breakdown_label(label: str) -> str:
    """Swap the internal breakdown sentinels for their display strings. The sentinels are globally
    unique tokens, so a substring replace covers every label shape — standalone, action-prefixed
    ("signed_up - <sentinel>"), and "::"-joined multi-breakdown values — without fragile splitting."""
    return label.replace(BREAKDOWN_OTHER_STRING_LABEL, BREAKDOWN_OTHER_DISPLAY).replace(
        BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_NULL_DISPLAY
    )


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
