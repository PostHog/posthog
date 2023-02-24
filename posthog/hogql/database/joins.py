from typing import Callable, List

from posthog.hogql import ast


def join_with_persons_table(from_table: str, to_table: str, requested_fields: List[str]):
    if not requested_fields:
        raise ValueError("No fields requested from persons table. Why are we joining it?")

    # contains the list of fields we will select from this table
    fields_to_select: List[ast.Expr] = []

    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=["version"])]
    )
    for field in requested_fields:
        if field != "id":
            fields_to_select.append(ast.Alias(alias=field, expr=argmax_version(ast.Field(chain=[field]))))

    id = ast.Field(chain=["id"])

    return ast.JoinExpr(
        join_type="INNER JOIN",
        table=ast.SelectQuery(
            select=fields_to_select + [id],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            group_by=[id],
            having=ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=argmax_version(ast.Field(chain=["is_deleted"])),
                right=ast.Constant(value=0),
            ),
        ),
        alias=to_table,
        constraint=ast.CompareOperation(
            op=ast.CompareOperationType.Eq,
            left=ast.Field(chain=[from_table, "person_id"]),
            right=ast.Field(chain=[to_table, "id"]),
        ),
    )


def join_with_max_person_distinct_id_table(from_table: str, to_table: str, requested_fields: List[str]):
    if not requested_fields:
        requested_fields = ["person_id"]

    # contains the list of fields we will select from this table
    fields_to_select: List[ast.Expr] = []

    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=["version"])]
    )
    for field in requested_fields:
        if field != "distinct_id":
            fields_to_select.append(ast.Alias(alias=field, expr=argmax_version(ast.Field(chain=[field]))))

    distinct_id = ast.Field(chain=["distinct_id"])

    return ast.JoinExpr(
        join_type="INNER JOIN",
        table=ast.SelectQuery(
            select=fields_to_select + [distinct_id],
            select_from=ast.JoinExpr(table=ast.Field(chain=["person_distinct_ids"])),
            group_by=[distinct_id],
            having=ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=argmax_version(ast.Field(chain=["is_deleted"])),
                right=ast.Constant(value=0),
            ),
        ),
        alias=to_table,
        constraint=ast.CompareOperation(
            op=ast.CompareOperationType.Eq,
            left=ast.Field(chain=[from_table, "distinct_id"]),
            right=ast.Field(chain=[to_table, "distinct_id"]),
        ),
    )
