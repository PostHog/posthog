from posthog.hogql import ast


def explain_csp_report(node: ast.Expr, args: list[ast.Expr]) -> ast.Expr:
    return ast.Tuple(
        exprs=[
            ast.Constant(value="__hx_tag"),
            ast.Constant(value="ExplainCSPReport"),
            ast.Constant(value="properties"),
            args[0],
        ]
    )
