from typing import Optional, Union

from posthog.hogql import ast
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS, HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_POSTHOG_FUNCTIONS
from posthog.hogql.parser import parse_expr


def is_aggregation_function(function_name: str) -> bool:
    """Check if a function name is an aggregation function."""
    # Normalize function name to lowercase for case-insensitive comparison
    normalized_name = function_name.lower()

    # First check the dedicated HOGQL_AGGREGATIONS dictionary
    normalized_hogql_aggregations = [func.lower() for func in HOGQL_AGGREGATIONS.keys()]
    if normalized_name in normalized_hogql_aggregations:
        return True

    # Also check other function dictionaries for aggregate functions
    for functions_dict in [HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_POSTHOG_FUNCTIONS]:
        if normalized_name in functions_dict:
            func_meta = functions_dict[normalized_name]
            if hasattr(func_meta, "aggregate") and func_meta.aggregate:
                return True

    return False


def extract_aggregation_and_inner_expr(hogql_expr: Union[str, ast.Expr]) -> tuple[Optional[str], ast.Expr]:
    """
    Extract the aggregation function and inner expression from a HogQL expression.

    Args:
        hogql_expr: Either a HogQL expression string or an already parsed AST expression

    Returns:
        A tuple of (aggregation_function_name, inner_expression)
        - aggregation_function_name: The name of the aggregation function (e.g., "sum"), or None if not an aggregation
        - inner_expression: The inner expression AST node

    Examples:
        "sum(properties.revenue - properties.expense)" -> ("sum", <ArithmeticOperation node>)
        "properties.revenue" -> (None, <Field node>)
        "count()" -> ("count", <Constant value=1>)
    """
    # Parse the expression if it's a string
    if isinstance(hogql_expr, str):
        expr = parse_expr(hogql_expr)
    else:
        expr = hogql_expr

    # Check if the expression is a function call
    if isinstance(expr, ast.Call) and is_aggregation_function(expr.name):
        # It's an aggregation function
        aggregation_function = expr.name

        # Get the inner expression
        if expr.args and len(expr.args) > 0:
            # Most aggregation functions take the expression as the first argument
            inner_expression = expr.args[0]
        else:
            # For functions like count() with no arguments, we emit 1
            inner_expression = ast.Constant(value=1)

        return aggregation_function, inner_expression
    else:
        # Not an aggregation function - return the whole expression as the inner part
        return None, expr


def build_aggregation_call(aggregation_function: str, inner_expr: ast.Expr, distinct: bool = False) -> ast.Call:
    """
    Build an aggregation function call AST node.

    Args:
        aggregation_function: The aggregation function name (e.g., "sum")
        inner_expr: The inner expression to aggregate
        distinct: Whether to use DISTINCT (for functions that support it)

    Returns:
        An ast.Call node representing the aggregation
    """
    return ast.Call(name=aggregation_function, args=[inner_expr], distinct=distinct)
