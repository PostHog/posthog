from posthog.hogql import ast


def sparkline(node: ast.Expr, args: list[ast.Expr]) -> ast.Expr:
    return ast.Tuple(
        exprs=[
            ast.Constant(value="__hx_tag"),
            ast.Constant(value="Sparkline"),
            ast.Constant(value="data"),
            args[0],
        ]
    )
