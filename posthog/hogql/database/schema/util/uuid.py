from posthog.hogql import ast


def uuid_string_expr_to_uuid_expr(uuid_expr: ast.Expr) -> ast.Expr:
    return ast.Call(name="toUUID", args=[uuid_expr])


def uuid_string_expr_to_uint128_expr(uuid_expr: ast.Expr) -> ast.Expr:
    return ast.Call(name="_toUInt128", args=[(uuid_string_expr_to_uuid_expr(uuid_expr))])


def uuid_expr_to_timestamp_expr(uuid_expr: ast.Expr) -> ast.Expr:
    return ast.Call(name="UUIDv7ToDateTime", args=[uuid_expr])


def uuid_uint128_expr_to_timestamp_expr_v2(uuid_expr: ast.Expr) -> ast.Expr:
    # use this for compat with sessions v2's ORDER BY
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


def uuid_uint128_expr_to_timestamp_expr_v3(uuid_expr: ast.Expr) -> ast.Expr:
    return ast.Call(
        name="fromUnixTimestamp64Milli",
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
        ],
    )


def uuid_uint128_to_uuid_expr(uuid: ast.Expr) -> ast.Expr:
    return ast.Call(
        name="reinterpretAsUUID",
        args=[
            ast.Call(
                name="bitOr",
                args=[
                    ast.Call(
                        name="bitShiftLeft",
                        args=[uuid, ast.Constant(value=64)],
                    ),
                    ast.Call(
                        name="bitShiftRight",
                        args=[uuid, ast.Constant(value=64)],
                    ),
                ],
            )
        ],
    )
