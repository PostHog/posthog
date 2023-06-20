from typing import List

from posthog.hogql import ast
from posthog.hogql.errors import HogQLException


def sparkline(node: ast.Expr, args: List[ast.Expr]) -> ast.Expr:
    if len(args) != 1:
        raise HogQLException("sparkline() takes exactly one argument", node=node)

    return ast.Tuple(
        exprs=[
            ast.Constant(value="__hogql_chart_type"),
            ast.Constant(value="sparkline"),
            ast.Constant(value="results"),
            args[0],
        ]
    )
