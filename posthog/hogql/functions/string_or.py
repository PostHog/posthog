from posthog.hogql import ast


def string_or(node: ast.Expr, args: list[ast.Expr]) -> ast.Expr:
    return ast.Call(
        name="ifNull",
        args=[
            ast.Call(
                name="coalesce",
                args=[
                    ast.Call(name="nullIf", args=[ast.Call(name="toString", args=[a]), ast.Constant(value="")])
                    for a in args
                ],
            ),
            ast.Constant(value=""),
        ],
    )
