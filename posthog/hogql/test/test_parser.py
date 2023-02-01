from antlr4 import CommonTokenStream, InputStream
from antlr4.tree.Tree import ParseTree

from posthog.hogql import ast
from posthog.hogql.grammar.HogQLLexer import HogQLLexer
from posthog.hogql.grammar.HogQLParser import HogQLParser
from posthog.hogql.parser import parse_expr, parse_statement
from posthog.test.base import BaseTest


def string_to_parse_tree_expr(query: str) -> ParseTree:
    input_stream = InputStream(query)
    lexer = HogQLLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = HogQLParser(stream)
    return parser.columnExpr()


class TestParser(BaseTest):
    def test_numbers(self):
        self.assertEqual(parse_expr("1"), ast.Constant(value=1))
        self.assertEqual(parse_expr("1.2"), ast.Constant(value=1.2))
        self.assertEqual(parse_expr("-1"), ast.Constant(value=-1))
        self.assertEqual(parse_expr("-1.1"), ast.Constant(value=-1.1))
        self.assertEqual(parse_expr("0"), ast.Constant(value=0))
        self.assertEqual(parse_expr("0.0"), ast.Constant(value=0))

    def test_booleans(self):
        self.assertEqual(parse_expr("true"), ast.Constant(value=True))
        self.assertEqual(parse_expr("TRUE"), ast.Constant(value=True))
        self.assertEqual(parse_expr("false"), ast.Constant(value=False))

    def test_null(self):
        self.assertEqual(parse_expr("null"), ast.Constant(value=None))

    def test_strings(self):
        self.assertEqual(parse_expr("'null'"), ast.Constant(value="null"))
        self.assertEqual(parse_expr("'n''ull'"), ast.Constant(value="n'ull"))
        self.assertEqual(parse_expr("'n''''ull'"), ast.Constant(value="n''ull"))
        self.assertEqual(parse_expr("'n\null'"), ast.Constant(value="n\null"))  # newline passed into string
        self.assertEqual(parse_expr("'n\\null'"), ast.Constant(value="n\null"))  # slash and 'n' passed into string
        self.assertEqual(parse_expr("'n\\\\ull'"), ast.Constant(value="n\\ull"))  # slash and 'n' passed into string

    def test_binary_operations(self):
        self.assertEqual(
            parse_expr("1 + 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Add
            ),
        )
        self.assertEqual(
            parse_expr("1 + -2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=-2), op=ast.BinaryOperationType.Add
            ),
        )
        self.assertEqual(
            parse_expr("1 - 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Sub
            ),
        )
        self.assertEqual(
            parse_expr("1 * 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Mult
            ),
        )
        self.assertEqual(
            parse_expr("1 / 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Div
            ),
        )
        self.assertEqual(
            parse_expr("1 % 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Mod
            ),
        )
        self.assertEqual(
            parse_expr("1 + 2 + 2"),
            ast.BinaryOperation(
                left=ast.BinaryOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Add
                ),
                right=ast.Constant(value=2),
                op=ast.BinaryOperationType.Add,
            ),
        )
        self.assertEqual(
            parse_expr("1 * 1 * 2"),
            ast.BinaryOperation(
                left=ast.BinaryOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=1), op=ast.BinaryOperationType.Mult
                ),
                right=ast.Constant(value=2),
                op=ast.BinaryOperationType.Mult,
            ),
        )
        self.assertEqual(
            parse_expr("1 + 1 * 2"),
            ast.BinaryOperation(
                left=ast.Constant(value=1),
                right=ast.BinaryOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.BinaryOperationType.Mult
                ),
                op=ast.BinaryOperationType.Add,
            ),
        )
        self.assertEqual(
            parse_expr("1 * 1 + 2"),
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
            parse_expr("1 = 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.Eq
            ),
        )
        self.assertEqual(
            parse_expr("1 == 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.Eq
            ),
        )
        self.assertEqual(
            parse_expr("1 != 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.NotEq
            ),
        )
        self.assertEqual(
            parse_expr("1 < 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.Lt
            ),
        )
        self.assertEqual(
            parse_expr("1 <= 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.LtE
            ),
        )
        self.assertEqual(
            parse_expr("1 > 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.Gt
            ),
        )
        self.assertEqual(
            parse_expr("1 >= 2"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationType.GtE
            ),
        )

    def test_null_comparison_operations(self):
        self.assertEqual(
            parse_expr("1 is null"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=None), op=ast.CompareOperationType.Eq
            ),
        )
        self.assertEqual(
            parse_expr("1 is not null"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=None), op=ast.CompareOperationType.NotEq
            ),
        )

    def test_like_comparison_operations(self):
        self.assertEqual(
            parse_expr("1 like 'a%sd'"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationType.Like
            ),
        )
        self.assertEqual(
            parse_expr("1 not like 'a%sd'"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationType.NotLike
            ),
        )
        self.assertEqual(
            parse_expr("1 ilike 'a%sd'"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationType.ILike
            ),
        )
        self.assertEqual(
            parse_expr("1 not ilike 'a%sd'"),
            ast.CompareOperation(
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationType.NotILike
            ),
        )

    def test_boolean_operations(self):
        self.assertEqual(
            parse_expr("true or false"),
            ast.BooleanOperation(
                values=[ast.Constant(value=True), ast.Constant(value=False)], op=ast.BooleanOperationType.Or
            ),
        )
        self.assertEqual(
            parse_expr("true and false"),
            ast.BooleanOperation(
                values=[ast.Constant(value=True), ast.Constant(value=False)], op=ast.BooleanOperationType.And
            ),
        )
        self.assertEqual(
            parse_expr("true and not false"),
            ast.BooleanOperation(
                values=[ast.Constant(value=True), ast.NotOperation(expr=ast.Constant(value=False))],
                op=ast.BooleanOperationType.And,
            ),
        )
        self.assertEqual(
            parse_expr("true or false or not true or 2"),
            ast.BooleanOperation(
                values=[
                    ast.Constant(value=True),
                    ast.Constant(value=False),
                    ast.NotOperation(expr=ast.Constant(value=True)),
                    ast.Constant(value=2),
                ],
                op=ast.BooleanOperationType.Or,
            ),
        )
        self.assertEqual(
            parse_expr("true or false and not true or 2"),
            ast.BooleanOperation(
                values=[
                    ast.Constant(value=True),
                    ast.BooleanOperation(
                        values=[ast.Constant(value=False), ast.NotOperation(expr=ast.Constant(value=True))],
                        op=ast.BooleanOperationType.And,
                    ),
                    ast.Constant(value=2),
                ],
                op=ast.BooleanOperationType.Or,
            ),
        )

    def test_unary_operations(self):
        self.assertEqual(
            parse_expr("not true"),
            ast.NotOperation(expr=ast.Constant(value=True)),
        )

    def test_parens(self):
        self.assertEqual(
            parse_expr("(1)"),
            ast.Constant(value=1),
        )
        self.assertEqual(
            parse_expr("(1 + 1)"),
            ast.BinaryOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=1), op=ast.BinaryOperationType.Add
            ),
        )
        self.assertEqual(
            parse_expr("1 + (1 + 1)"),
            ast.BinaryOperation(
                left=ast.Constant(value=1),
                right=ast.BinaryOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=1), op=ast.BinaryOperationType.Add
                ),
                op=ast.BinaryOperationType.Add,
            ),
        )

    def test_field_access(self):
        self.assertEqual(
            parse_expr("event"),
            ast.FieldAccess(field="event"),
        )
        self.assertEqual(
            parse_expr("event like '$%'"),
            ast.CompareOperation(
                left=ast.FieldAccess(field="event"), right=ast.Constant(value="$%"), op=ast.CompareOperationType.Like
            ),
        )

    def test_property_access(self):
        self.assertEqual(
            parse_expr("properties.something == 1"),
            ast.CompareOperation(
                left=ast.FieldAccessChain(chain=["properties", "something"]),
                right=ast.Constant(value=1),
                op=ast.CompareOperationType.Eq,
            ),
        )
        self.assertEqual(
            parse_expr("properties.something"),
            ast.FieldAccessChain(chain=["properties", "something"]),
        )
        self.assertEqual(
            parse_expr("properties.$something"),
            ast.FieldAccessChain(chain=["properties", "$something"]),
        )
        self.assertEqual(
            parse_expr("person.properties.something"),
            ast.FieldAccessChain(chain=["person", "properties", "something"]),
        )
        self.assertEqual(
            parse_expr("this.can.go.on.for.miles"),
            ast.FieldAccessChain(chain=["this", "can", "go", "on", "for", "miles"]),
        )

    def test_calls(self):
        self.assertEqual(
            parse_expr("avg()"),
            ast.Call(name="avg", args=[]),
        )
        self.assertEqual(
            parse_expr("avg(1,2,3)"),
            ast.Call(name="avg", args=[ast.Constant(value=1), ast.Constant(value=2), ast.Constant(value=3)]),
        )

    def test_expr_with_ignored_python_comment(self):
        self.assertEqual(
            parse_expr("1 # asd"),
            ast.Constant(value=1),
        )
        self.assertEqual(
            parse_expr("1 # 'asd'"),
            ast.Constant(value=1),
        )
        self.assertEqual(
            parse_expr("1 # '🍄'"),
            ast.Constant(value=1),
        )

    def test_select_columns(self):
        self.assertEqual(parse_statement("select 1"), ast.SelectQuery(select=[ast.Constant(value=1)]))

    def test_select_where(self):
        self.assertEqual(
            parse_statement("select 1 where true"),
            ast.SelectQuery(select=[ast.Constant(value=1)], where=ast.Constant(value=True)),
        )
        self.assertEqual(
            parse_statement("select 1 where 1 == 2"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                where=ast.CompareOperation(
                    op=ast.CompareOperationType.Eq, left=ast.Constant(value=1), right=ast.Constant(value=2)
                ),
            ),
        )

    def test_select_prewhere(self):
        self.assertEqual(
            parse_statement("select 1 prewhere true"),
            ast.SelectQuery(select=[ast.Constant(value=1)], prewhere=ast.Constant(value=True)),
        )
        self.assertEqual(
            parse_statement("select 1 prewhere 1 == 2"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                prewhere=ast.CompareOperation(
                    op=ast.CompareOperationType.Eq, left=ast.Constant(value=1), right=ast.Constant(value=2)
                ),
            ),
        )

    def test_select_having(self):
        self.assertEqual(
            parse_statement("select 1 having true"),
            ast.SelectQuery(select=[ast.Constant(value=1)], having=ast.Constant(value=True)),
        )
        self.assertEqual(
            parse_statement("select 1 having 1 == 2"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                having=ast.CompareOperation(
                    op=ast.CompareOperationType.Eq, left=ast.Constant(value=1), right=ast.Constant(value=2)
                ),
            ),
        )

    def test_select_complex(self):
        self.assertEqual(
            parse_statement("select 1 prewhere 2 != 3 where 1 == 2 having 'string' like '%a%'"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                where=ast.CompareOperation(
                    op=ast.CompareOperationType.Eq, left=ast.Constant(value=1), right=ast.Constant(value=2)
                ),
                prewhere=ast.CompareOperation(
                    op=ast.CompareOperationType.NotEq, left=ast.Constant(value=2), right=ast.Constant(value=3)
                ),
                having=ast.CompareOperation(
                    op=ast.CompareOperationType.Like, left=ast.Constant(value="string"), right=ast.Constant(value="%a%")
                ),
            ),
        )
