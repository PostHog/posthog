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
    if not properties_path:
        properties_path = ["properties"]

    from posthog.hogql.property import apply_path_cleaning

    path_expr = ast.Field(chain=[*properties_path, "$pathname"])
    cleaned_expr = apply_path_cleaning(path_expr, team)

    return ExpressionField(
        name=name,
        expr=cleaned_expr,
        isolate_scope=True,
    )
