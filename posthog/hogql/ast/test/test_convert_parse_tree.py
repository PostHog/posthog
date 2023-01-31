from antlr4 import CommonTokenStream, InputStream
from antlr4.tree.Tree import ParseTree

from posthog.hogql.ast import ast
from posthog.hogql.ast.convert_parse_tree import parse_tree_to_expr
from posthog.hogql.grammar.HogQLLexer import HogQLLexer
from posthog.hogql.grammar.HogQLParser import HogQLParser
from posthog.test.base import BaseTest


def string_to_parse_tree_expr(query: str) -> ParseTree:
    input_stream = InputStream(query)
    lexer = HogQLLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = HogQLParser(stream)
    return parser.columnExpr()


def expr_to_ast(expr: str) -> ast.Expr:
    return parse_tree_to_expr(string_to_parse_tree_expr(expr))


class TestConvertParseTree(BaseTest):
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
        self.assertEqual(expr_to_ast("'n\\null'"), ast.Constant(value="n\\null"))
        # TODO: make sure this is iron tight

    def test_binary_operations(self):
        self.assertEqual(
            expr_to_ast("1 + 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Add
            ),
        )
        self.assertEqual(
            expr_to_ast("1 + -2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=-2), op=ast.BinaryOperationType.Add
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

    def test_math_comparison_operations(self):
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

    def test_null_comparison_operations(self):
        self.assertEqual(
            expr_to_ast("1 is null"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=None), op=ast.CompareOperationType.Eq
            ),
        )
        self.assertEqual(
            expr_to_ast("1 is not null"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=None), op=ast.CompareOperationType.NotEq
            ),
        )

    def test_like_comparison_operations(self):
        self.assertEqual(
            expr_to_ast("1 like 'a%sd'"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationType.Like
            ),
        )
        self.assertEqual(
            expr_to_ast("1 not like 'a%sd'"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationType.NotLike
            ),
        )
        self.assertEqual(
            expr_to_ast("1 ilike 'a%sd'"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationType.ILike
            ),
        )
        self.assertEqual(
            expr_to_ast("1 not ilike 'a%sd'"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationType.NotILike
            ),
        )

    def test_boolean_operations(self):
        self.assertEqual(
            expr_to_ast("true or false"),
            ast.BooleanOperation(
                left=ast.Constant(value=True), right=ast.Constant(value=False), op=ast.BooleanOperationType.Or
            ),
        )
        self.assertEqual(
            expr_to_ast("true and false"),
            ast.BooleanOperation(
                left=ast.Constant(value=True), right=ast.Constant(value=False), op=ast.BooleanOperationType.And
            ),
        )
        self.assertEqual(
            expr_to_ast("true and not false"),
            ast.BooleanOperation(
                left=ast.Constant(value=True),
                right=ast.NotOperation(expr=ast.Constant(value=False)),
                op=ast.BooleanOperationType.And,
            ),
        )
        self.assertEqual(
            expr_to_ast("true or false or not true or 2"),
            ast.BooleanOperation(
                left=ast.BooleanOperation(
                    left=ast.BooleanOperation(
                        left=ast.Constant(value=True), right=ast.Constant(value=False), op=ast.BooleanOperationType.Or
                    ),
                    right=ast.NotOperation(expr=ast.Constant(value=True)),
                    op=ast.BooleanOperationType.Or,
                ),
                right=ast.Constant(value=2),
                op=ast.BooleanOperationType.Or,
            ),
        )
        self.assertEqual(
            expr_to_ast("true or false and not true or 2"),
            ast.BooleanOperation(
                left=ast.BooleanOperation(
                    left=ast.Constant(value=True),
                    right=ast.BooleanOperation(
                        left=ast.Constant(value=False),
                        right=ast.NotOperation(expr=ast.Constant(value=True)),
                        op=ast.BooleanOperationType.And,
                    ),
                    op=ast.BooleanOperationType.Or,
                ),
                right=ast.Constant(value=2),
                op=ast.BooleanOperationType.Or,
            ),
        )

    def test_unary_operations(self):
        self.assertEqual(
            expr_to_ast("not true"),
            ast.NotOperation(expr=ast.Constant(value=True)),
        )

    def test_parens(self):
        self.assertEqual(
            expr_to_ast("(1)"),
            ast.Parens(expr=ast.Constant(value=1)),
        )
        self.assertEqual(
            expr_to_ast("(1 + 1)"),
            ast.Parens(
                expr=ast.BinaryOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=1), op=ast.BinaryOperationType.Add
                )
            ),
        )
        self.assertEqual(
            expr_to_ast("1 + (1 + 1)"),
            ast.BinaryOperation(
                left=ast.Constant(value=1),
                right=ast.Parens(
                    expr=ast.BinaryOperation(
                        left=ast.Constant(value=1), right=ast.Constant(value=1), op=ast.BinaryOperationType.Add
                    )
                ),
                op=ast.BinaryOperationType.Add,
            ),
        )
