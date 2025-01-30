from posthog.hogql import ast
from posthog.hogql.utils import deserialize_hx_ast
from posthog.test.base import BaseTest


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
