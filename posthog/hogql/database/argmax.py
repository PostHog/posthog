from typing import Callable, List, Optional, Dict


def argmax_select(
    table_name: str,
    select_fields: Dict[str, List[str]],
    group_fields: List[str],
    argmax_field: str,
    deleted_field: Optional[str] = None,
):
    from posthog.hogql import ast

    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=[table_name, argmax_field])]
    )

    fields_to_group: List[ast.Expr] = []
    fields_to_select: List[ast.Expr] = []
    for name, chain in select_fields.items():
        if name not in group_fields:
            fields_to_select.append(
                ast.Alias(
                    alias=name,
                    expr=argmax_version(ast.Field(chain=[table_name] + chain)),
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

    return select_query
