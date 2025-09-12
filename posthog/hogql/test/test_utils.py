from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.utils import deserialize_hx_ast


class TestUtils(BaseTest):
    def test_deserialize_hx_ast(self):
        assert deserialize_hx_ast(
            {
                "__hx_ast": "Constant",
                "value": 1,
            }
        ) == ast.Constant(value=1)

        assert deserialize_hx_ast(
            {
                "__hx_ast": "Call",
                "name": "hello",
                "args": [
                    {
                        "__hx_ast": "Constant",
                        "value": "is it me?",
                    }
                ],
            }
        ) == ast.Call(name="hello", args=[ast.Constant(value="is it me?")])

        assert deserialize_hx_ast(
            {
                "__hx_ast": "SelectQuery",
                "group_by": [{"__hx_ast": "Field", "chain": ["event"]}],
                "select": [
                    {"__hx_tag": "blink", "children": [{"__hx_ast": "Field", "chain": ["event"]}]},
                    {
                        "__hx_ast": "Call",
                        "args": [{"__hx_ast": "Field", "chain": ["*"]}],
                        "distinct": False,
                        "name": "count",
                    },
                    "ewrew222",
                ],
                "select_from": {"__hx_ast": "JoinExpr", "table": {"__hx_ast": "Field", "chain": ["events"]}},
                "where": {
                    "__hx_ast": "CompareOperation",
                    "left": {"__hx_ast": "Field", "chain": ["timestamp"]},
                    "op": ">",
                    "right": {
                        "__hx_ast": "ArithmeticOperation",
                        "left": {"__hx_ast": "Call", "args": [], "distinct": False, "name": "now"},
                        "op": "-",
                        "right": {
                            "__hx_ast": "Call",
                            "args": [{"__hx_ast": "Constant", "value": 1}],
                            "distinct": False,
                            "name": "toIntervalDay",
                        },
                    },
                },
            }
        ) == ast.SelectQuery(
            select=[
                ast.HogQLXTag(
                    kind="blink", attributes=[ast.HogQLXAttribute(name="children", value=[ast.Field(chain=["event"])])]
                ),
                ast.Call(name="count", args=[ast.Field(chain=["*"])]),
                ast.Constant(value="ewrew222"),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                right=ast.ArithmeticOperation(
                    left=ast.Call(name="now", args=[]),
                    right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)]),
                    op=ast.ArithmeticOperationOp.Sub,
                ),
                op=ast.CompareOperationOp.Gt,
            ),
            group_by=[ast.Field(chain=["event"])],
        )

    def test_deserialize_hx_ast_error(self):
        with self.assertRaises(ValueError) as e:
            deserialize_hx_ast(
                {
                    "__hx_ast": "Constant",
                    "value": 1,
                    "unexpected": 2,
                }
            )
        self.assertEqual(str(e.exception), "Unexpected field 'unexpected' for AST node 'Constant'")

        with self.assertRaises(ValueError) as e:
            deserialize_hx_ast(
                {
                    "__hx_ast": "Invalid",
                    "value": 1,
                }
            )
        self.assertEqual(str(e.exception), "Invalid or missing '__hx_ast' kind: Invalid")
