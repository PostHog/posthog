from posthog.hogql import ast


def sparkline(node: ast.Expr, args: list[ast.Expr]) -> ast.Expr:
    exprs: list[ast.Expr] = [
        ast.Constant(value="__hx_tag"),
        ast.Constant(value="Sparkline"),
        ast.Constant(value="data"),
        args[0],
    ]

    if len(args) == 2:
        exprs.extend(
            [
                ast.Constant(value="labels"),
                args[1],
            ]
        )

    return ast.Tuple(exprs=exprs)
