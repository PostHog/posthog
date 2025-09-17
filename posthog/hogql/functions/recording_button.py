from posthog.hogql import ast


def recording_button(node: ast.Expr, args: list[ast.Expr]) -> ast.Expr:
    return ast.Tuple(
        exprs=[
            ast.Constant(value="__hx_tag"),
            ast.Constant(value="RecordingButton"),
            ast.Constant(value="sessionId"),
            args[0],
            ast.Constant(value="recordingStatus"),
            args[1] if len(args) > 1 else ast.Field(chain=["properties", "$recording_status"]),
        ]
    )
