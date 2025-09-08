from collections.abc import Callable
from typing import Optional

from posthog.hogql.ast import SelectQuery
from posthog.hogql.parser import parse_expr


def argmax_select(
    table_name: str,
    select_fields: dict[str, list[str | int]],
    group_fields: list[str],
    argmax_field: str,
    deleted_field: Optional[str] = None,
    timestamp_field_to_clamp: Optional[str] = None,
) -> "SelectQuery":
    from posthog.hogql import ast

    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=[table_name, argmax_field])]
    )

    fields_to_group: list[ast.Expr] = []
    fields_to_select: list[ast.Expr] = []
    for name, chain in select_fields.items():
        if name not in group_fields:
            fields_to_select.append(
                ast.Alias(
                    alias=name,
                    expr=argmax_version(ast.Field(chain=[table_name, *chain])),
                )
            )
    for key in group_fields:
        fields_to_group.append(ast.Field(chain=[table_name, key]))
        fields_to_select.append(ast.Alias(alias=key, expr=ast.Field(chain=[table_name, key])))

    select_query = ast.SelectQuery(
        select=fields_to_select,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=fields_to_group,
    )
    if deleted_field:
        select_query.having = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=argmax_version(ast.Field(chain=[table_name, deleted_field])),
            right=ast.Constant(value=0),
        )
    if timestamp_field_to_clamp:
        clause = ast.CompareOperation(
            op=ast.CompareOperationOp.Lt,
            left=argmax_version(ast.Field(chain=[table_name, timestamp_field_to_clamp])),
            right=parse_expr("now() + interval 1 day"),
        )
        select_query.having = clause if select_query.having is None else ast.And(exprs=[select_query.having, clause])

    return select_query
