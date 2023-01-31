from unittest import TestCase

from antlr4 import CommonTokenStream, InputStream
from antlr4.tree.Tree import ParseTree

from posthog.hogql.ast import ast
from posthog.hogql.ast.convert_parse_tree import parse_tree_to_expr
from posthog.hogql.grammar.HogQLLexer import HogQLLexer
from posthog.hogql.grammar.HogQLParser import HogQLParser


def string_to_parse_tree_expr(query: str) -> ParseTree:
    input_stream = InputStream(query)
    lexer = HogQLLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = HogQLParser(stream)
    return parser.columnExpr()


def expr_to_ast(expr: str) -> ast.Expr:
    return parse_tree_to_expr(string_to_parse_tree_expr(expr))


class TestConvertParseTree(TestCase):
    def test_numbers(self):
        self.assertEqual(expr_to_ast("1"), ast.Constant(value=1))
        self.assertEqual(expr_to_ast("1.2"), ast.Constant(value=1.2))
        self.assertEqual(expr_to_ast("-1"), ast.Constant(value=-1))
        self.assertEqual(expr_to_ast("-1.1"), ast.Constant(value=-1.1))
        self.assertEqual(expr_to_ast("0"), ast.Constant(value=0))
        self.assertEqual(expr_to_ast("0.0"), ast.Constant(value=0))

    def test_booleans(self):
        self.assertEqual(expr_to_ast("true"), ast.Constant(value=True))
        self.assertEqual(expr_to_ast("TRUE"), ast.Constant(value=True))
        self.assertEqual(expr_to_ast("false"), ast.Constant(value=False))

    def test_null(self):
        self.assertEqual(expr_to_ast("null"), ast.Constant(value=None))

    def test_strings(self):
        self.assertEqual(expr_to_ast("'null'"), ast.Constant(value="null"))
        self.assertEqual(expr_to_ast("'n''ull'"), ast.Constant(value="n'ull"))
        self.assertEqual(expr_to_ast("'n''''ull'"), ast.Constant(value="n''ull"))
        self.assertEqual(expr_to_ast("'n\null'"), ast.Constant(value="n\null"))
        self.assertEqual(expr_to_ast("'n\\\\''ull'"), ast.Constant(value="n\\ull"))

    def test_binary_operations(self):
        self.assertEqual(
            expr_to_ast("1 + 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Add
            ),
        )
        self.assertEqual(
            expr_to_ast("1 - 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Sub
            ),
        )
        self.assertEqual(
            expr_to_ast("1 * 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Mult
            ),
        )
        self.assertEqual(
            expr_to_ast("1 / 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Div
            ),
        )
        self.assertEqual(
            expr_to_ast("1 % 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Mod
            ),
        )
        self.assertEqual(
            expr_to_ast("1 + 2 + 2"),
            ast.BinaryOperation(
                left=ast.BinaryOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Add
                ),
                right=ast.Constant(value=2),
                op=ast.BinaryOperationType.Add,
            ),
        )
        self.assertEqual(
            expr_to_ast("1 * 1 * 2"),
            ast.BinaryOperation(
                left=ast.BinaryOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=1), op=ast.BinaryOperationType.Mult
                ),
                right=ast.Constant(value=2),
                op=ast.BinaryOperationType.Mult,
            ),
        )
        self.assertEqual(
            expr_to_ast("1 + 1 * 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1),
                right=ast.BinaryOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Mult
                ),
                op=ast.BinaryOperationType.Add,
            ),
        )
        self.assertEqual(
            expr_to_ast("1 * 1 + 2"),
            ast.BinaryOperation(
                left=ast.BinaryOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=1), op=ast.BinaryOperationType.Mult
                ),
                right=ast.Constant(value=2),
                op=ast.BinaryOperationType.Add,
            ),
        )

    def test_comparison_operations(self):
        self.assertEqual(
            expr_to_ast("1 = 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.Eq
            ),
        )
        self.assertEqual(
            expr_to_ast("1 == 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.Eq
            ),
        )
        self.assertEqual(
            expr_to_ast("1 != 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.NotEq
            ),
        )
        self.assertEqual(
            expr_to_ast("1 < 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.Lt
            ),
        )
        self.assertEqual(
            expr_to_ast("1 <= 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.LtE
            ),
        )
        self.assertEqual(
            expr_to_ast("1 > 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.Gt
            ),
        )
        self.assertEqual(
            expr_to_ast("1 >= 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.GtE
            ),
        )

    def test_unary_operations(self):
        self.assertEqual(
            expr_to_ast("not true"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Add
            ),
        )
