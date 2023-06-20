from posthog.hogql import ast
from posthog.hogql.database.argmax import argmax_select
from posthog.test.base import BaseTest


class TestArgmax(BaseTest):
    def test_argmax_select(self):
        response = argmax_select(
            table_name="raw_persons",
            select_fields={"moo": ["properties", "moo"], "id": ["id"]},
            group_fields=["id"],
            argmax_field="version",
        )
        expected = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="moo",
                    expr=ast.Call(
                        name="argMax",
                        args=[
                            ast.Field(chain=["raw_persons", "properties", "moo"]),
                            ast.Field(chain=["raw_persons", "version"]),
                        ],
                    ),
                ),
                ast.Alias(alias="id", expr=ast.Field(chain=["raw_persons", "id"])),
            ],
            # mypy wants all the named arguments, but we don't really need them
            select_from=ast.JoinExpr(table=ast.Field(chain=["raw_persons"])),  # type: ignore
            group_by=[ast.Field(chain=["raw_persons", "id"])],
        )
        self.assertEqual(response, expected)

    def test_argmax_select_deleted(self):
        response = argmax_select(
            table_name="raw_persons",
            select_fields={"moo": ["properties", "moo"], "id": ["id"]},
            group_fields=["id"],
            argmax_field="version",
            deleted_field="is_deleted",
        )
        expected = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="moo",
                    expr=ast.Call(
                        name="argMax",
                        args=[
                            ast.Field(chain=["raw_persons", "properties", "moo"]),
                            ast.Field(chain=["raw_persons", "version"]),
                        ],
                    ),
                ),
                ast.Alias(alias="id", expr=ast.Field(chain=["raw_persons", "id"])),
            ],
            # mypy wants all the named arguments, but we don't really need them
            select_from=ast.JoinExpr(table=ast.Field(chain=["raw_persons"])),  # type: ignore
            group_by=[ast.Field(chain=["raw_persons", "id"])],
            # mypy wants all the named arguments, but we don't really need them
            having=ast.CompareOperation(  # type: ignore
                op=ast.CompareOperationOp.Eq,
                left=ast.Call(
                    name="argMax",
                    args=[ast.Field(chain=["raw_persons", "is_deleted"]), ast.Field(chain=["raw_persons", "version"])],
                ),
                right=ast.Constant(value=0),
            ),
        )
        self.assertEqual(response, expected)
