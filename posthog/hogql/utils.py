from typing import Union

from pydantic import BaseModel

from posthog.hogql import ast
from posthog.hogql.constants import HOGQL_AGGREGATIONS
from posthog.models import Action


def has_aggregation(expr: ast.AST) -> bool:
    if isinstance(expr, ast.Call):
        return expr.name in HOGQL_AGGREGATIONS
    if any(has_aggregation(child) for child in expr.children()):
        return True
    return False


def action_to_expr(action: Action) -> ast.Expr:
    raise NotImplementedError("action_to_expr not implemented")


def property_to_expr(properties: Union[BaseModel, dict]) -> ast.Expr:
    raise NotImplementedError("property_to_expr not implemented")
