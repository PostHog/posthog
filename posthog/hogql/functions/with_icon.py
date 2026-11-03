from posthog.hogql import ast


def with_icon(node: ast.Expr, args: list[ast.Expr]) -> ast.Expr:
    return ast.Tuple(
        exprs=[
            ast.Constant(value="__hx_tag"),
            ast.Constant(value="BrandMarkLabel"),
            ast.Constant(value="label"),
            args[0],
            ast.Constant(value="mark"),
            args[1],
        ]
    )
