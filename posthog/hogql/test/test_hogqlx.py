from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.hogqlx import convert_dict_to_hx, convert_tag_to_hx, convert_to_hx


class TestHogQLX(BaseTest):
    def test_convert_tag_to_hx(self):
        tag = ast.HogQLXTag(kind="Sparkline", attributes=[])
        self.assertEqual(
            convert_tag_to_hx(tag), ast.Tuple(exprs=[ast.Constant(value="__hx_tag"), ast.Constant(value="Sparkline")])
        )

        tag = ast.HogQLXTag(
            kind="Sparkline", attributes=[ast.HogQLXAttribute(name="color", value=ast.Constant(value="red"))]
        )
        self.assertEqual(
            convert_tag_to_hx(tag),
            ast.Tuple(
                exprs=[
                    ast.Constant(value="__hx_tag"),
                    ast.Constant(value="Sparkline"),
                    ast.Constant(value="color"),
                    ast.Constant(value="red"),
                ]
            ),
        )

    def test_convert_dict_to_hx(self):
        d = ast.Dict(items=[])
        self.assertEqual(
            convert_dict_to_hx(d), ast.Tuple(exprs=[ast.Constant(value="__hx_tag"), ast.Constant(value="__hx_obj")])
        )

        d = ast.Dict(items=[(ast.Constant(value="color"), ast.Constant(value="red"))])
        self.assertEqual(
            convert_dict_to_hx(d),
            ast.Tuple(
                exprs=[
                    ast.Constant(value="__hx_tag"),
                    ast.Constant(value="__hx_obj"),
                    ast.Constant(value="color"),
                    ast.Constant(value="red"),
                ]
            ),
        )

    def test_convert_to_hx(self):
        self.assertEqual(convert_to_hx(1), ast.Constant(value=1))
        self.assertEqual(convert_to_hx(None), ast.Constant(value=None))
        self.assertEqual(convert_to_hx(False), ast.Constant(value=False))
        self.assertEqual(convert_to_hx("a"), ast.Constant(value="a"))
        self.assertEqual(convert_to_hx(ast.Constant(value=1)), ast.Constant(value=1))
        self.assertEqual(
            convert_to_hx(ast.HogQLXTag(kind="Sparkline", attributes=[])),
            ast.Tuple(exprs=[ast.Constant(value="__hx_tag"), ast.Constant(value="Sparkline")]),
        )
        self.assertEqual(
            convert_to_hx(ast.Dict(items=[])),
            ast.Tuple(exprs=[ast.Constant(value="__hx_tag"), ast.Constant(value="__hx_obj")]),
        )
        self.assertEqual(
            convert_to_hx(ast.Array(exprs=[ast.Constant(value=1), ast.Constant(value=2), ast.Constant(value=3)])),
            ast.Tuple(exprs=[ast.Constant(value=1), ast.Constant(value=2), ast.Constant(value=3)]),
        )
        self.assertEqual(
            convert_to_hx([1, 2, 3]),
            ast.Tuple(exprs=[ast.Constant(value=1), ast.Constant(value=2), ast.Constant(value=3)]),
        )
