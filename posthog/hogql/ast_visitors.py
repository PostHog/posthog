from posthog.hogql import ast
from posthog.hogql.constants import HOGQL_AGGREGATIONS


def has_aggregation(expr: ast.AST) -> bool:
    if isinstance(expr, ast.Call):
        return expr.name in HOGQL_AGGREGATIONS
    if any(has_aggregation(child) for child in expr.children()):
        return True
    return False
