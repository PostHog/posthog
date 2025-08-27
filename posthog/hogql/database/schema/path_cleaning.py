from typing import TYPE_CHECKING, Optional

from posthog.hogql import ast
from posthog.hogql.database.models import ExpressionField

if TYPE_CHECKING:
    from posthog.models import Team


def create_path_cleaned_pathname(
    name: str,
    team: "Team",
    properties_path: Optional[list[str]] = None
) -> ExpressionField:
    """
    Create a virtual field that applies team's path cleaning rules to pathname.

    This field applies the same path cleaning logic used in web analytics
    to clean up pathname values by applying regex replacements configured
    in the team's path_cleaning_filters.
    """
    if not properties_path:
        properties_path = ["properties"]

    # Import here to avoid circular import
    from posthog.hogql.property import apply_path_cleaning

    # Build the expression using the team's path cleaning rules
    path_expr = ast.Field(chain=[*properties_path, "$pathname"])
    cleaned_expr = apply_path_cleaning(path_expr, team)

    return ExpressionField(
        name=name,
        expr=cleaned_expr,
        isolate_scope=True,
    )