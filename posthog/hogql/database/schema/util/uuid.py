from posthog.hogql import ast


def uuid_string_expr_to_uuid_expr(uuid_expr: ast.Expr) -> ast.Expr:
    return ast.Call(name="toUUID", args=[uuid_expr])


def uuid_string_expr_to_uint128_expr(uuid_expr: ast.Expr) -> ast.Expr:
    return ast.Call(name="_toUInt128", args=[(uuid_string_expr_to_uuid_expr(uuid_expr))])


def uuid_expr_to_timestamp_expr(uuid_expr: ast.Expr) -> ast.Expr:
    return ast.Call(name="UUIDv7ToDateTime", args=[uuid_expr])


def uuid_uint128_expr_to_timestamp_expr(uuid_expr: ast.Expr) -> ast.Expr:
    return ast.Call(
        name="fromUnixTimestamp",
        args=[
            ast.Call(
                name="intDiv",
                args=[
                    ast.Call(
                        name="_toUInt64",
                        args=[
                            ast.Call(
                                name="bitShiftRight",
                                args=[uuid_expr, ast.Constant(value=80)],
                            )
                        ],
                    ),
                    ast.Constant(value=1000),
                ],
            )
        ],
    )
