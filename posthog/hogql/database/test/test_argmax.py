from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.database.argmax import argmax_select


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
                        name="tupleElement",
                        args=[
                            ast.Call(
                                name="argMax",
                                args=[
                                    ast.Call(
                                        name="tuple",
                                        args=[
                                            ast.Field(chain=["raw_persons", "properties", "moo"]),
                                        ],
                                    ),
                                    ast.Field(chain=["raw_persons", "version"]),
                                ],
                            ),
                            ast.Constant(value=1),
                        ],
                    ),
                ),
                ast.Alias(alias="id", expr=ast.Field(chain=["raw_persons", "id"])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["raw_persons"])),
            group_by=[ast.Field(chain=["raw_persons", "id"])],
        )
        assert response == expected

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
                        name="tupleElement",
                        args=[
                            ast.Call(
                                name="argMax",
                                args=[
                                    ast.Call(
                                        name="tuple", args=[ast.Field(chain=["raw_persons", "properties", "moo"])]
                                    ),
                                    ast.Field(chain=["raw_persons", "version"]),
                                ],
                            ),
                            ast.Constant(value=1),
                        ],
                    ),
                ),
                ast.Alias(alias="id", expr=ast.Field(chain=["raw_persons", "id"])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["raw_persons"])),
            group_by=[ast.Field(chain=["raw_persons", "id"])],
            having=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Call(
                    name="tupleElement",
                    args=[
                        ast.Call(
                            name="argMax",
                            args=[
                                ast.Call(
                                    name="tuple",
                                    args=[
                                        ast.Field(chain=["raw_persons", "is_deleted"]),
                                    ],
                                ),
                                ast.Field(chain=["raw_persons", "version"]),
                            ],
                        ),
                        ast.Constant(value=1),
                    ],
                ),
                right=ast.Constant(value=0),
            ),
        )
        assert response == expected
