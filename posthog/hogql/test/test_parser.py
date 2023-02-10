from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.test.base import BaseTest


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

    def test_and_or(self):
        self.assertEqual(
            parse_expr("true or false"),
            ast.Or(exprs=[ast.Constant(value=True), ast.Constant(value=False)]),
        )
        self.assertEqual(
            parse_expr("true and false"),
            ast.And(exprs=[ast.Constant(value=True), ast.Constant(value=False)]),
        )
        self.assertEqual(
            parse_expr("true and not false"),
            ast.And(
                exprs=[ast.Constant(value=True), ast.Not(expr=ast.Constant(value=False))],
            ),
        )
        self.assertEqual(
            parse_expr("true or false or not true or 2"),
            ast.Or(
                exprs=[
                    ast.Constant(value=True),
                    ast.Constant(value=False),
                    ast.Not(expr=ast.Constant(value=True)),
                    ast.Constant(value=2),
                ],
            ),
        )
        self.assertEqual(
            parse_expr("true or false and not true or 2"),
            ast.Or(
                exprs=[
                    ast.Constant(value=True),
                    ast.And(
                        exprs=[ast.Constant(value=False), ast.Not(expr=ast.Constant(value=True))],
                    ),
                    ast.Constant(value=2),
                ],
            ),
        )

    def test_unary_operations(self):
        self.assertEqual(
            parse_expr("not true"),
            ast.Not(expr=ast.Constant(value=True)),
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
            ast.Field(chain=["event"]),
        )
        self.assertEqual(
            parse_expr("event like '$%'"),
            ast.CompareOperation(
                left=ast.Field(chain=["event"]), right=ast.Constant(value="$%"), op=ast.CompareOperationType.Like
            ),
        )

    def test_property_access(self):
        self.assertEqual(
            parse_expr("properties.something == 1"),
            ast.CompareOperation(
                left=ast.Field(chain=["properties", "something"]),
                right=ast.Constant(value=1),
                op=ast.CompareOperationType.Eq,
            ),
        )
        self.assertEqual(
            parse_expr("properties.something"),
            ast.Field(chain=["properties", "something"]),
        )
        self.assertEqual(
            parse_expr("properties.$something"),
            ast.Field(chain=["properties", "$something"]),
        )
        self.assertEqual(
            parse_expr("person.properties.something"),
            ast.Field(chain=["person", "properties", "something"]),
        )
        self.assertEqual(
            parse_expr("this.can.go.on.for.miles"),
            ast.Field(chain=["this", "can", "go", "on", "for", "miles"]),
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

    def test_alias(self):
        self.assertEqual(
            parse_expr("1 as asd"),
            ast.Alias(alias="asd", expr=ast.Constant(value=1)),
        )
        self.assertEqual(
            parse_expr("1 as `asd`"),
            ast.Alias(alias="asd", expr=ast.Constant(value=1)),
        )
        self.assertEqual(
            parse_expr("1 as `🍄`"),
            ast.Alias(alias="🍄", expr=ast.Constant(value=1)),
        )
        self.assertEqual(
            parse_expr("(1 as b) as `🍄`"),
            ast.Alias(alias="🍄", expr=ast.Alias(alias="b", expr=ast.Constant(value=1))),
        )

    def test_expr_with_ignored_sql_comment(self):
        self.assertEqual(
            parse_expr("1 -- asd"),
            ast.Constant(value=1),
        )
        self.assertEqual(
            parse_expr("1 -- 'asd'"),
            ast.Constant(value=1),
        )
        self.assertEqual(
            parse_expr("1 -- '🍄'"),
            ast.Constant(value=1),
        )

    def test_placeholders(self):
        self.assertEqual(
            parse_expr("{foo}"),
            ast.Placeholder(field="foo"),
        )
        self.assertEqual(
            parse_expr("{foo}", {"foo": ast.Constant(value="bar")}),
            ast.Constant(value="bar"),
        )
        self.assertEqual(
            parse_expr("timestamp < {timestamp}", {"timestamp": ast.Constant(value=123)}),
            ast.CompareOperation(
                op=ast.CompareOperationType.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=123),
            ),
        )
