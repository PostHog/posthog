import math
from typing import Literal, Optional, cast

from posthog.test.base import BaseTest, MemoryLeakTestMixin

from posthog.hogql import ast
from posthog.hogql.ast import (
    ArithmeticOperation,
    ArithmeticOperationOp,
    Array,
    Block,
    Call,
    CompareOperation,
    CompareOperationOp,
    Constant,
    Dict,
    ExprStatement,
    Field,
    Function,
    IfStatement,
    JoinExpr,
    Program,
    SelectQuery,
    SelectSetNode,
    SelectSetQuery,
    VariableAssignment,
    VariableDeclaration,
    WhileStatement,
)
from posthog.hogql.errors import ExposedHogQLError, SyntaxError
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_program, parse_select, parse_string_template
from posthog.hogql.visitor import clear_locations


def parser_test_factory(backend: Literal["python", "cpp"]):
    base_classes = (MemoryLeakTestMixin, BaseTest) if backend == "cpp" else (BaseTest,)

    class TestParser(*base_classes):  # type: ignore
        MEMORY_INCREASE_PER_PARSE_LIMIT_B = 10_000
        MEMORY_INCREASE_INCREMENTAL_FACTOR_LIMIT = 0.1
        MEMORY_PRIMING_RUNS_N = 2
        MEMORY_LEAK_CHECK_RUNS_N = 100

        maxDiff = None

        def _string_template(self, template: str, placeholders: Optional[dict[str, ast.Expr]] = None) -> ast.Expr:
            return clear_locations(parse_string_template(template, placeholders=placeholders, backend=backend))

        def _expr(self, expr: str, placeholders: Optional[dict[str, ast.Expr]] = None) -> ast.Expr:
            return clear_locations(parse_expr(expr, placeholders=placeholders, backend=backend))

        def _select(
            self, query: str, placeholders: Optional[dict[str, ast.Expr]] = None
        ) -> ast.SelectQuery | ast.SelectSetQuery | ast.HogQLXTag:
            return cast(
                ast.SelectQuery | ast.SelectSetQuery | ast.HogQLXTag,
                clear_locations(parse_select(query, placeholders=placeholders, backend=backend)),
            )

        def _program(self, program: str) -> ast.Program:
            return cast(ast.Program, clear_locations(cast(ast.Expr, parse_program(program, backend=backend))))

        def test_numbers(self):
            self.assertEqual(self._expr("1"), ast.Constant(value=1))
            self.assertEqual(self._expr("1.2"), ast.Constant(value=1.2))
            self.assertEqual(self._expr("-1"), ast.Constant(value=-1))
            self.assertEqual(self._expr("-1.1"), ast.Constant(value=-1.1))
            self.assertEqual(self._expr("0"), ast.Constant(value=0))
            self.assertEqual(self._expr("0.0"), ast.Constant(value=0))
            self.assertEqual(self._expr("-inf"), ast.Constant(value=float("-inf")))
            self.assertEqual(self._expr("inf"), ast.Constant(value=float("inf")))
            # nan-s don't like to be compared
            parsed_nan = self._expr("nan")
            self.assertTrue(isinstance(parsed_nan, ast.Constant))
            self.assertTrue(math.isnan(cast(ast.Constant, parsed_nan).value))
            self.assertEqual(self._expr("1e-18"), ast.Constant(value=1e-18))
            self.assertEqual(self._expr("2.34e+20"), ast.Constant(value=2.34e20))

        def test_booleans(self):
            self.assertEqual(self._expr("true"), ast.Constant(value=True))
            self.assertEqual(self._expr("TRUE"), ast.Constant(value=True))
            self.assertEqual(self._expr("false"), ast.Constant(value=False))

        def test_null(self):
            self.assertEqual(self._expr("null"), ast.Constant(value=None))

        def test_nullish(self):
            self.assertEqual(
                self._expr("1 ?? 2"),
                ast.Call(
                    name="ifNull",
                    args=[
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                    ],
                ),
            )

        def test_null_property(self):
            self.assertEqual(
                self._expr("a?.b"),
                ast.ArrayAccess(
                    array=ast.Field(chain=["a"]),
                    property=ast.Constant(value="b"),
                    nullish=True,
                ),
            )

        def test_null_tuple(self):
            self.assertEqual(
                self._expr("a?.1"),
                ast.TupleAccess(
                    tuple=ast.Field(chain=["a"]),
                    index=1,
                    nullish=True,
                ),
            )

        def test_null_property_nested(self):
            self.assertEqual(
                self._expr("a?.b?.['c']"),
                ast.ArrayAccess(
                    array=ast.ArrayAccess(array=ast.Field(chain=["a"]), property=ast.Constant(value="b"), nullish=True),
                    property=ast.Constant(value="c"),
                    nullish=True,
                ),
            )

        def test_conditional(self):
            self.assertEqual(
                self._expr("1 > 2 ? 1 : 2"),
                ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Gt,
                            left=ast.Constant(value=1),
                            right=ast.Constant(value=2),
                        ),
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                    ],
                ),
            )

        def test_arrays(self):
            self.assertEqual(self._expr("[]"), ast.Array(exprs=[]))
            self.assertEqual(self._expr("[1]"), ast.Array(exprs=[ast.Constant(value=1)]))
            self.assertEqual(
                self._expr("[1, avg()]"),
                ast.Array(exprs=[ast.Constant(value=1), ast.Call(name="avg", args=[])]),
            )
            self.assertEqual(self._expr("[1,]"), ast.Array(exprs=[ast.Constant(value=1)]))
            self.assertEqual(
                self._expr("[1, avg(),]"),
                ast.Array(exprs=[ast.Constant(value=1), ast.Call(name="avg", args=[])]),
            )
            self.assertEqual(
                self._expr("properties['value']"),
                ast.ArrayAccess(
                    array=ast.Field(chain=["properties"]),
                    property=ast.Constant(value="value"),
                ),
            )
            self.assertEqual(
                self._expr("properties[(select 'value')]"),
                ast.ArrayAccess(
                    array=ast.Field(chain=["properties"]),
                    property=ast.SelectQuery(select=[ast.Constant(value="value")]),
                ),
            )
            self.assertEqual(
                self._expr("[1,2,3][1]"),
                ast.ArrayAccess(
                    array=ast.Array(
                        exprs=[
                            ast.Constant(value=1),
                            ast.Constant(value=2),
                            ast.Constant(value=3),
                        ]
                    ),
                    property=ast.Constant(value=1),
                ),
            )

        def test_tuples(self):
            self.assertEqual(
                self._expr("(1, avg())"),
                ast.Tuple(exprs=[ast.Constant(value=1), ast.Call(name="avg", args=[])]),
            )
            self.assertEqual(
                self._expr("(1, avg(),)"),
                ast.Tuple(exprs=[ast.Constant(value=1), ast.Call(name="avg", args=[])]),
            )
            self.assertEqual(
                self._expr("(1,)"),
                ast.Tuple(exprs=[ast.Constant(value=1)]),
            )
            # needs at least two values to be a tuple
            self.assertEqual(self._expr("(1)"), ast.Constant(value=1))

        def test_lambdas(self):
            self.assertEqual(
                self._expr("(x, y) -> x * y"),
                ast.Lambda(
                    args=["x", "y"],
                    expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Mult,
                        left=ast.Field(chain=["x"]),
                        right=ast.Field(chain=["y"]),
                    ),
                ),
            )
            self.assertEqual(
                self._expr("x, y -> x * y"),
                ast.Lambda(
                    args=["x", "y"],
                    expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Mult,
                        left=ast.Field(chain=["x"]),
                        right=ast.Field(chain=["y"]),
                    ),
                ),
            )
            self.assertEqual(
                self._expr("(x) -> x * y"),
                ast.Lambda(
                    args=["x"],
                    expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Mult,
                        left=ast.Field(chain=["x"]),
                        right=ast.Field(chain=["y"]),
                    ),
                ),
            )
            self.assertEqual(
                self._expr("x -> x * y"),
                ast.Lambda(
                    args=["x"],
                    expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Mult,
                        left=ast.Field(chain=["x"]),
                        right=ast.Field(chain=["y"]),
                    ),
                ),
            )
            self.assertEqual(
                self._expr("arrayMap(x -> x * 2)"),
                ast.Call(
                    name="arrayMap",
                    args=[
                        ast.Lambda(
                            args=["x"],
                            expr=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Mult,
                                left=ast.Field(chain=["x"]),
                                right=ast.Constant(value=2),
                            ),
                        )
                    ],
                ),
            )
            self.assertEqual(
                self._expr("arrayMap((x) -> x * 2)"),
                ast.Call(
                    name="arrayMap",
                    args=[
                        ast.Lambda(
                            args=["x"],
                            expr=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Mult,
                                left=ast.Field(chain=["x"]),
                                right=ast.Constant(value=2),
                            ),
                        )
                    ],
                ),
            )
            self.assertEqual(
                self._expr("arrayMap((x, y) -> x * y)"),
                ast.Call(
                    name="arrayMap",
                    args=[
                        ast.Lambda(
                            args=["x", "y"],
                            expr=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Mult,
                                left=ast.Field(chain=["x"]),
                                right=ast.Field(chain=["y"]),
                            ),
                        )
                    ],
                ),
            )

        def test_lambda_blocks(self):
            self.assertEqual(
                self._expr("(x, y) -> { print('hello'); return x * y }"),
                ast.Lambda(
                    args=["x", "y"],
                    expr=ast.Block(
                        declarations=[
                            ast.ExprStatement(expr=ast.Call(name="print", args=[ast.Constant(value="hello")])),
                            ast.ReturnStatement(
                                expr=ast.ArithmeticOperation(
                                    op=ast.ArithmeticOperationOp.Mult,
                                    left=ast.Field(chain=["x"]),
                                    right=ast.Field(chain=["y"]),
                                )
                            ),
                        ]
                    ),
                ),
            )

        def test_call_expr(self):
            self.assertEqual(
                self._expr("asd.asd(123)"),
                ast.ExprCall(
                    expr=ast.Field(chain=["asd", "asd"]),
                    args=[ast.Constant(value=123)],
                ),
            )
            self.assertEqual(
                self._expr("asd['asd'](123)"),
                ast.ExprCall(
                    expr=ast.ArrayAccess(array=ast.Field(chain=["asd"]), property=ast.Constant(value="asd")),
                    args=[ast.Constant(value=123)],
                ),
            )
            self.assertEqual(
                self._expr("(x -> x * 2)(3)"),
                ast.ExprCall(
                    expr=ast.Lambda(
                        args=["x"],
                        expr=ast.ArithmeticOperation(
                            op=ast.ArithmeticOperationOp.Mult, left=ast.Field(chain=["x"]), right=ast.Constant(value=2)
                        ),
                    ),
                    args=[ast.Constant(value=3)],
                ),
            )

        def test_call_expr_sql(self):
            self.assertEqual(
                self._expr("asd.asd(select 1)"),
                ast.ExprCall(
                    expr=ast.Field(chain=["asd", "asd"]),
                    args=[ast.SelectQuery(select=[ast.Constant(value=1)])],
                ),
            )
            self.assertEqual(
                self._expr("sql(select 1)"),
                ast.Call(
                    name="sql",
                    args=[ast.SelectQuery(select=[ast.Constant(value=1)])],
                ),
            )

        def test_strings(self):
            self.assertEqual(self._expr("'null'"), ast.Constant(value="null"))
            self.assertEqual(self._expr("'n''ull'"), ast.Constant(value="n'ull"))
            self.assertEqual(self._expr("'n''''ull'"), ast.Constant(value="n''ull"))
            self.assertEqual(self._expr("'n\null'"), ast.Constant(value="n\null"))  # newline passed into string
            self.assertEqual(self._expr("'n\\null'"), ast.Constant(value="n\null"))  # slash and 'n' passed into string
            self.assertEqual(self._expr("'n\\\\ull'"), ast.Constant(value="n\\ull"))  # slash and 'n' passed into string

        def test_arithmetic_operations(self):
            self.assertEqual(
                self._expr("1 + 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )
            self.assertEqual(
                self._expr("1 + -2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=-2),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )
            self.assertEqual(
                self._expr("1 - 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Sub,
                ),
            )
            self.assertEqual(
                self._expr("1 * 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Mult,
                ),
            )
            self.assertEqual(
                self._expr("1 / 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Div,
                ),
            )
            self.assertEqual(
                self._expr("1 % 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Mod,
                ),
            )
            self.assertEqual(
                self._expr("1 + 2 + 2"),
                ast.ArithmeticOperation(
                    left=ast.ArithmeticOperation(
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                        op=ast.ArithmeticOperationOp.Add,
                    ),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )
            self.assertEqual(
                self._expr("1 * 1 * 2"),
                ast.ArithmeticOperation(
                    left=ast.ArithmeticOperation(
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=1),
                        op=ast.ArithmeticOperationOp.Mult,
                    ),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Mult,
                ),
            )
            self.assertEqual(
                self._expr("1 + 1 * 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.ArithmeticOperation(
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                        op=ast.ArithmeticOperationOp.Mult,
                    ),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )
            self.assertEqual(
                self._expr("1 * 1 + 2"),
                ast.ArithmeticOperation(
                    left=ast.ArithmeticOperation(
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=1),
                        op=ast.ArithmeticOperationOp.Mult,
                    ),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )

        def test_math_comparison_operations(self):
            self.assertEqual(
                self._expr("1 = 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.Eq,
                ),
            )
            self.assertEqual(
                self._expr("1 == 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.Eq,
                ),
            )
            self.assertEqual(
                self._expr("1 != 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.NotEq,
                ),
            )
            self.assertEqual(
                self._expr("1 < 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.Lt,
                ),
            )
            self.assertEqual(
                self._expr("1 <= 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.LtEq,
                ),
            )
            self.assertEqual(
                self._expr("1 > 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.Gt,
                ),
            )
            self.assertEqual(
                self._expr("1 >= 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.GtEq,
                ),
            )

        def test_null_comparison_operations(self):
            self.assertEqual(
                self._expr("1 is null"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=None),
                    op=ast.CompareOperationOp.Eq,
                ),
            )
            self.assertEqual(
                self._expr("1 is not null"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=None),
                    op=ast.CompareOperationOp.NotEq,
                ),
            )

        def test_like_comparison_operations(self):
            self.assertEqual(
                self._expr("1 like 'a%sd'"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value="a%sd"),
                    op=ast.CompareOperationOp.Like,
                ),
            )
            self.assertEqual(
                self._expr("1 not like 'a%sd'"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value="a%sd"),
                    op=ast.CompareOperationOp.NotLike,
                ),
            )
            self.assertEqual(
                self._expr("1 ilike 'a%sd'"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value="a%sd"),
                    op=ast.CompareOperationOp.ILike,
                ),
            )
            self.assertEqual(
                self._expr("1 not ilike 'a%sd'"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value="a%sd"),
                    op=ast.CompareOperationOp.NotILike,
                ),
            )

        def test_and_or(self):
            self.assertEqual(
                self._expr("true or false"),
                ast.Or(exprs=[ast.Constant(value=True), ast.Constant(value=False)]),
            )
            self.assertEqual(
                self._expr("true and false"),
                ast.And(exprs=[ast.Constant(value=True), ast.Constant(value=False)]),
            )
            self.assertEqual(
                self._expr("true and not false"),
                ast.And(
                    exprs=[
                        ast.Constant(value=True),
                        ast.Not(expr=ast.Constant(value=False)),
                    ],
                ),
            )
            self.assertEqual(
                self._expr("true or false or not true or 2"),
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
                self._expr("true or false and not true or 2"),
                ast.Or(
                    exprs=[
                        ast.Constant(value=True),
                        ast.And(
                            exprs=[
                                ast.Constant(value=False),
                                ast.Not(expr=ast.Constant(value=True)),
                            ],
                        ),
                        ast.Constant(value=2),
                    ],
                ),
            )

        def test_unary_operations(self):
            self.assertEqual(
                self._expr("not true"),
                ast.Not(expr=ast.Constant(value=True)),
            )

        def test_parens(self):
            self.assertEqual(
                self._expr("(1)"),
                ast.Constant(value=1),
            )
            self.assertEqual(
                self._expr("(1 + 1)"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=1),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )
            self.assertEqual(
                self._expr("1 + (1 + 1)"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.ArithmeticOperation(
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=1),
                        op=ast.ArithmeticOperationOp.Add,
                    ),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )

        def test_field_access(self):
            self.assertEqual(
                self._expr("event"),
                ast.Field(chain=["event"]),
            )
            self.assertEqual(
                self._expr("event like '$%'"),
                ast.CompareOperation(
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value="$%"),
                    op=ast.CompareOperationOp.Like,
                ),
            )

        def test_property_access(self):
            self.assertEqual(
                self._expr("properties.something == 1"),
                ast.CompareOperation(
                    left=ast.Field(chain=["properties", "something"]),
                    right=ast.Constant(value=1),
                    op=ast.CompareOperationOp.Eq,
                ),
            )
            self.assertEqual(
                self._expr("properties.something"),
                ast.Field(chain=["properties", "something"]),
            )
            self.assertEqual(
                self._expr("properties.$something"),
                ast.Field(chain=["properties", "$something"]),
            )
            self.assertEqual(
                self._expr("person.properties.something"),
                ast.Field(chain=["person", "properties", "something"]),
            )
            self.assertEqual(
                self._expr("this.can.go.on.for.miles"),
                ast.Field(chain=["this", "can", "go", "on", "for", "miles"]),
            )

        def test_calls(self):
            self.assertEqual(
                self._expr("avg()"),
                ast.Call(name="avg", args=[]),
            )
            self.assertEqual(
                self._expr("avg(1,2,3)"),
                ast.Call(
                    name="avg",
                    args=[
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                        ast.Constant(value=3),
                    ],
                ),
            )

        def test_calls_with_params(self):
            self.assertEqual(
                self._expr("quantile(0.95)(foo)"),
                ast.Call(
                    name="quantile",
                    args=[ast.Field(chain=["foo"])],
                    params=[ast.Constant(value=0.95)],
                ),
            )

        def test_alias(self):
            self.assertEqual(
                self._expr("1 as asd"),
                ast.Alias(alias="asd", expr=ast.Constant(value=1)),
            )
            self.assertEqual(
                self._expr("1 as `asd`"),
                ast.Alias(alias="asd", expr=ast.Constant(value=1)),
            )
            self.assertEqual(
                self._expr("1 as `🍄`"),
                ast.Alias(alias="🍄", expr=ast.Constant(value=1)),
            )
            self.assertEqual(
                self._expr("(1 as b) as `🍄`"),
                ast.Alias(alias="🍄", expr=ast.Alias(alias="b", expr=ast.Constant(value=1))),
            )

        def test_expr_with_ignored_sql_comment(self):
            self.assertEqual(
                self._expr("1 -- asd"),
                ast.Constant(value=1),
            )
            self.assertEqual(
                self._expr("1 -- 'asd'"),
                ast.Constant(value=1),
            )
            self.assertEqual(
                self._expr("1 -- '🍄'"),
                ast.Constant(value=1),
            )

        def test_placeholders(self):
            self.assertEqual(
                self._expr("{foo}"),
                ast.Placeholder(expr=ast.Field(chain=["foo"])),
            )
            self.assertEqual(
                self._expr("{foo}", {"foo": ast.Constant(value="bar")}),
                ast.Constant(value="bar"),
            )
            self.assertEqual(
                self._expr("timestamp < {timestamp}", {"timestamp": ast.Constant(value=123)}),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=123),
                ),
            )
            self.assertEqual(
                self._expr("timestamp={timestamp}", {"timestamp": ast.Constant(value=123)}),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=123),
                ),
            )

        def test_intervals(self):
            self.assertEqual(
                self._expr("interval 1 month"),
                ast.Call(name="toIntervalMonth", args=[ast.Constant(value=1)]),
            )
            self.assertEqual(
                self._expr("interval '1 month'"),
                ast.Call(name="toIntervalMonth", args=[ast.Constant(value=1)]),
            )
            self.assertEqual(
                self._expr("now() - interval 1 week"),
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Sub,
                    left=ast.Call(name="now", args=[]),
                    right=ast.Call(name="toIntervalWeek", args=[ast.Constant(value=1)]),
                ),
            )
            self.assertEqual(
                self._expr("now() - interval '1 week'"),
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Sub,
                    left=ast.Call(name="now", args=[]),
                    right=ast.Call(name="toIntervalWeek", args=[ast.Constant(value=1)]),
                ),
            )
            self.assertEqual(
                self._expr("interval event year"),
                ast.Call(name="toIntervalYear", args=[ast.Field(chain=["event"])]),
            )

        def test_select_columns(self):
            self.assertEqual(
                self._select("select 1"),
                ast.SelectQuery(select=[ast.Constant(value=1)]),
            )
            self.assertEqual(
                self._select("select 1, 4, 'string'"),
                ast.SelectQuery(
                    select=[
                        ast.Constant(value=1),
                        ast.Constant(value=4),
                        ast.Constant(value="string"),
                    ]
                ),
            )

        def test_select_columns_distinct(self):
            self.assertEqual(
                self._select("select distinct 1"),
                ast.SelectQuery(select=[ast.Constant(value=1)], distinct=True),
            )

        def test_select_where(self):
            self.assertEqual(
                self._select("select 1 where true"),
                ast.SelectQuery(select=[ast.Constant(value=1)], where=ast.Constant(value=True)),
            )
            self.assertEqual(
                self._select("select 1 where 1 == 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    where=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                ),
            )

        def test_select_prewhere(self):
            self.assertEqual(
                self._select("select 1 prewhere true"),
                ast.SelectQuery(select=[ast.Constant(value=1)], prewhere=ast.Constant(value=True)),
            )
            self.assertEqual(
                self._select("select 1 prewhere 1 == 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    prewhere=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                ),
            )

        def test_select_having(self):
            self.assertEqual(
                self._select("select 1 having true"),
                ast.SelectQuery(select=[ast.Constant(value=1)], having=ast.Constant(value=True)),
            )
            self.assertEqual(
                self._select("select 1 having 1 == 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    having=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                ),
            )

        def test_select_complex_wheres(self):
            self.assertEqual(
                self._select("select 1 prewhere 2 != 3 where 1 == 2 having 'string' like '%a%'"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    where=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                    prewhere=ast.CompareOperation(
                        op=ast.CompareOperationOp.NotEq,
                        left=ast.Constant(value=2),
                        right=ast.Constant(value=3),
                    ),
                    having=ast.CompareOperation(
                        op=ast.CompareOperationOp.Like,
                        left=ast.Constant(value="string"),
                        right=ast.Constant(value="%a%"),
                    ),
                ),
            )

        def test_select_from(self):
            self.assertEqual(
                self._select("select 1 from events"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events as e"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events e"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
                ),
            )
            self.assertEqual(
                self._select("select 1 from complex.table"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["complex", "table"])),
                ),
            )
            self.assertEqual(
                self._select("select 1 from complex.table as a"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["complex", "table"]), alias="a"),
                ),
            )
            self.assertEqual(
                self._select("select 1 from complex.table a"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["complex", "table"]), alias="a"),
                ),
            )
            self.assertEqual(
                self._select("select 1 from (select 1 from events)"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.SelectQuery(
                            select=[ast.Constant(value=1)],
                            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                        )
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from (select 1 from events) as sq"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.SelectQuery(
                            select=[ast.Constant(value=1)],
                            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                        ),
                        alias="sq",
                    ),
                ),
            )

        def test_select_from_placeholder(self):
            self.assertEqual(
                self._select("select 1 from {placeholder}"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Placeholder(expr=ast.Field(chain=["placeholder"]))),
                ),
            )
            self.assertEqual(
                self._select(
                    "select 1 from {placeholder}",
                    {"placeholder": ast.Field(chain=["events"])},
                ),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_select_from_join(self):
            self.assertEqual(
                self._select("select 1 from events JOIN events2 ON 1"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="JOIN",
                            table=ast.Field(chain=["events2"]),
                            constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select * from events LEFT OUTER JOIN events2 ON 1"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="LEFT OUTER JOIN",
                            table=ast.Field(chain=["events2"]),
                            constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LEFT OUTER JOIN events2 ON 1 ANY RIGHT JOIN events3 ON 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="LEFT OUTER JOIN",
                            table=ast.Field(chain=["events2"]),
                            constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                            next_join=ast.JoinExpr(
                                join_type="RIGHT ANY JOIN",
                                table=ast.Field(chain=["events3"]),
                                constraint=ast.JoinConstraint(expr=ast.Constant(value=2), constraint_type="ON"),
                            ),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events JOIN events2 USING 1"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="JOIN",
                            table=ast.Field(chain=["events2"]),
                            constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="USING"),
                        ),
                    ),
                ),
            )

        def test_select_from_join_multiple(self):
            node = self._select(
                """
                SELECT event, timestamp, e.distinct_id, p.id, p.properties.email
                FROM events e
                LEFT JOIN person_distinct_id pdi
                ON pdi.distinct_id = e.distinct_id
                LEFT JOIN persons p
                ON p.id = pdi.person_id
                """,
                self.team,
            )
            self.assertEqual(
                node,
                ast.SelectQuery(
                    select=[
                        ast.Field(chain=["event"]),
                        ast.Field(chain=["timestamp"]),
                        ast.Field(chain=["e", "distinct_id"]),
                        ast.Field(chain=["p", "id"]),
                        ast.Field(chain=["p", "properties", "email"]),
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        alias="e",
                        next_join=ast.JoinExpr(
                            join_type="LEFT JOIN",
                            table=ast.Field(chain=["person_distinct_id"]),
                            alias="pdi",
                            constraint=ast.JoinConstraint(
                                expr=ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["pdi", "distinct_id"]),
                                    right=ast.Field(chain=["e", "distinct_id"]),
                                ),
                                constraint_type="ON",
                            ),
                            next_join=ast.JoinExpr(
                                join_type="LEFT JOIN",
                                table=ast.Field(chain=["persons"]),
                                alias="p",
                                constraint=ast.JoinConstraint(
                                    expr=ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["p", "id"]),
                                        right=ast.Field(chain=["pdi", "person_id"]),
                                    ),
                                    constraint_type="ON",
                                ),
                            ),
                        ),
                    ),
                ),
            )

        def test_select_from_cross_join(self):
            self.assertEqual(
                self._select("select 1 from events CROSS JOIN events2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="CROSS JOIN",
                            table=ast.Field(chain=["events2"]),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events CROSS JOIN events2 CROSS JOIN events3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="CROSS JOIN",
                            table=ast.Field(chain=["events2"]),
                            next_join=ast.JoinExpr(
                                join_type="CROSS JOIN",
                                table=ast.Field(chain=["events3"]),
                            ),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events, events2 CROSS JOIN events3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="CROSS JOIN",
                            table=ast.Field(chain=["events2"]),
                            next_join=ast.JoinExpr(
                                join_type="CROSS JOIN",
                                table=ast.Field(chain=["events3"]),
                            ),
                        ),
                    ),
                ),
            )

        def test_select_array_join(self):
            self.assertEqual(
                self._select("select a from events ARRAY JOIN [1,2,3] as a"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["a"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    array_join_op="ARRAY JOIN",
                    array_join_list=[
                        ast.Alias(
                            expr=ast.Array(
                                exprs=[
                                    ast.Constant(value=1),
                                    ast.Constant(value=2),
                                    ast.Constant(value=3),
                                ]
                            ),
                            alias="a",
                        )
                    ],
                ),
            )
            self.assertEqual(
                self._select("select a from events INNER ARRAY JOIN [1,2,3] as a"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["a"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    array_join_op="INNER ARRAY JOIN",
                    array_join_list=[
                        ast.Alias(
                            expr=ast.Array(
                                exprs=[
                                    ast.Constant(value=1),
                                    ast.Constant(value=2),
                                    ast.Constant(value=3),
                                ]
                            ),
                            alias="a",
                        )
                    ],
                ),
            )
            self.assertEqual(
                self._select("select 1, b from events LEFT ARRAY JOIN [1,2,3] as a, [4,5,6] AS b"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1), ast.Field(chain=["b"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    array_join_op="LEFT ARRAY JOIN",
                    array_join_list=[
                        ast.Alias(
                            expr=ast.Array(
                                exprs=[
                                    ast.Constant(value=1),
                                    ast.Constant(value=2),
                                    ast.Constant(value=3),
                                ]
                            ),
                            alias="a",
                        ),
                        ast.Alias(
                            expr=ast.Array(
                                exprs=[
                                    ast.Constant(value=4),
                                    ast.Constant(value=5),
                                    ast.Constant(value=6),
                                ]
                            ),
                            alias="b",
                        ),
                    ],
                ),
            )

        def test_select_array_join_errors(self):
            with self.assertRaises(ExposedHogQLError) as e:
                self._select("select a from events ARRAY JOIN [1,2,3]")
            self.assertEqual(str(e.exception), "ARRAY JOIN arrays must have an alias")
            self.assertEqual(e.exception.start, 32)
            self.assertEqual(e.exception.end, 39)

            with self.assertRaises(ExposedHogQLError) as e:
                self._select("select a ARRAY JOIN [1,2,3]")
            self.assertEqual(
                str(e.exception),
                "Using ARRAY JOIN without a FROM clause is not permitted",
            )
            self.assertEqual(e.exception.start, 0)
            self.assertEqual(e.exception.end, 27)

        def test_select_group_by(self):
            self.assertEqual(
                self._select("select 1 from events GROUP BY 1, event"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    group_by=[ast.Constant(value=1), ast.Field(chain=["event"])],
                ),
            )

        def test_order_by(self):
            self.assertEqual(
                parse_order_expr("1 ASC"),
                ast.OrderExpr(
                    expr=ast.Constant(value=1, start=0, end=1),
                    order="ASC",
                    start=0,
                    end=5,
                ),
            )
            self.assertEqual(
                parse_order_expr("event"),
                ast.OrderExpr(
                    expr=ast.Field(chain=["event"], start=0, end=5),
                    order="ASC",
                    start=0,
                    end=5,
                ),
            )
            self.assertEqual(
                parse_order_expr("timestamp DESC"),
                ast.OrderExpr(
                    expr=ast.Field(chain=["timestamp"], start=0, end=9),
                    order="DESC",
                    start=0,
                    end=14,
                ),
            )
            # Note that the parser will skip anything after `--`, so the `DESC` behind will not be parsed
            self.assertEqual(
                parse_order_expr("timestamp -- a comment DESC"),
                ast.OrderExpr(
                    expr=ast.Field(chain=["timestamp"], start=0, end=9),
                    order="ASC",
                    start=0,
                    end=9,
                ),
            )

        def test_select_order_by(self):
            self.assertEqual(
                self._select("select 1 from events ORDER BY 1 ASC, event, timestamp DESC"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    order_by=[
                        ast.OrderExpr(expr=ast.Constant(value=1), order="ASC"),
                        ast.OrderExpr(expr=ast.Field(chain=["event"]), order="ASC"),
                        ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC"),
                    ],
                ),
            )

        def test_select_limit_offset(self):
            self.assertEqual(
                self._select("select 1 from events LIMIT 1"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=1),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 1 OFFSET 3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=1),
                    offset=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events OFFSET 3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=None,
                    offset=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events ORDER BY 1 LIMIT 1 WITH TIES"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    order_by=[ast.OrderExpr(expr=ast.Constant(value=1), order="ASC")],
                    limit=ast.Constant(value=1),
                    limit_with_ties=True,
                    offset=None,
                ),
            )
            self.assertEqual(
                self._select("select 1 from events ORDER BY 1 LIMIT 1, 3 WITH TIES"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    order_by=[ast.OrderExpr(expr=ast.Constant(value=1), order="ASC")],
                    limit=ast.Constant(value=1),
                    limit_with_ties=True,
                    offset=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 1 BY event LIMIT 2 OFFSET 3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=2),
                    offset=ast.Constant(value=3),
                    limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["event"])]),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 1 OFFSET 4 BY event LIMIT 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=2),
                    limit_by=ast.LimitByExpr(
                        n=ast.Constant(value=1), offset_value=ast.Constant(value=4), exprs=[ast.Field(chain=["event"])]
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 4, 1 BY event LIMIT 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=2),
                    limit_by=ast.LimitByExpr(
                        n=ast.Constant(value=1), offset_value=ast.Constant(value=4), exprs=[ast.Field(chain=["event"])]
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 1 OFFSET 4 BY event LIMIT 2 OFFSET 5"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=2),
                    offset=ast.Constant(value=5),
                    limit_by=ast.LimitByExpr(
                        n=ast.Constant(value=1), offset_value=ast.Constant(value=4), exprs=[ast.Field(chain=["event"])]
                    ),
                ),
            )

        def test_select_placeholders(self):
            self.assertEqual(
                self._select("select 1 where 1 == {hogql_val_1}"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    where=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Placeholder(expr=ast.Field(chain=["hogql_val_1"])),
                    ),
                ),
            )
            self.assertEqual(
                self._select(
                    "select 1 where 1 == {hogql_val_1}",
                    {"hogql_val_1": ast.Constant(value="bar")},
                ),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    where=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value="bar"),
                    ),
                ),
            )

        def test_placeholder_expressions(self):
            actual = self._select("select 1 where 1 == {1 ? hogql_val_1 : hogql_val_2}")
            expected = clear_locations(
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    where=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Placeholder(
                            expr=ast.Call(
                                name="if",
                                args=[
                                    ast.Constant(value=1),
                                    ast.Field(chain=["hogql_val_1"]),
                                    ast.Field(chain=["hogql_val_2"]),
                                ],
                            )
                        ),
                    ),
                )
            )
            self.assertEqual(actual, expected)

        def test_select_union_all(self):
            self.assertEqual(
                self._select("select 1 union all select 2 union all select 3"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(select=[ast.Constant(value=1)]),
                    subsequent_select_queries=[
                        SelectSetNode(set_operator="UNION ALL", select_query=query)
                        for query in (
                            ast.SelectQuery(select=[ast.Constant(value=2)]),
                            ast.SelectQuery(select=[ast.Constant(value=3)]),
                        )
                    ],
                ),
            )

        def test_nested_selects(self):
            self.assertEqual(
                self._select("(select 1 intersect select 2) union all (select 3 except select 4)"),
                SelectSetQuery(
                    initial_select_query=SelectSetQuery(
                        initial_select_query=SelectQuery(select=[Constant(value=1)]),
                        subsequent_select_queries=[
                            SelectSetNode(
                                select_query=SelectQuery(
                                    select=[Constant(value=2)],
                                ),
                                set_operator="INTERSECT",
                            )
                        ],
                    ),
                    subsequent_select_queries=[
                        SelectSetNode(
                            select_query=SelectSetQuery(
                                initial_select_query=SelectQuery(
                                    select=[Constant(value=3)],
                                ),
                                subsequent_select_queries=[
                                    SelectSetNode(
                                        select_query=SelectQuery(select=[Constant(value=4)]), set_operator="EXCEPT"
                                    )
                                ],
                            ),
                            set_operator="UNION ALL",
                        )
                    ],
                ),
            )

        def test_sample_clause(self):
            self.assertEqual(
                self._select("select 1 from events sample 1/10 offset 999"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        sample=ast.SampleExpr(
                            offset_value=ast.RatioExpr(left=ast.Constant(value=999)),
                            sample_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=10)),
                        ),
                    ),
                ),
            )

            self.assertEqual(
                self._select("select 1 from events sample 0.1 offset 999"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        sample=ast.SampleExpr(
                            offset_value=ast.RatioExpr(left=ast.Constant(value=999)),
                            sample_value=ast.RatioExpr(
                                left=ast.Constant(value=0.1),
                            ),
                        ),
                    ),
                ),
            )

            self.assertEqual(
                self._select("select 1 from events sample 10 offset 1/2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        sample=ast.SampleExpr(
                            offset_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=2)),
                            sample_value=ast.RatioExpr(
                                left=ast.Constant(value=10),
                            ),
                        ),
                    ),
                ),
            )

            self.assertEqual(
                self._select("select 1 from events sample 10"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        sample=ast.SampleExpr(
                            sample_value=ast.RatioExpr(
                                left=ast.Constant(value=10),
                            ),
                        ),
                    ),
                ),
            )

        def test_select_with_columns(self):
            self.assertEqual(
                self._select("with event as boo select boo from events"),
                ast.SelectQuery(
                    ctes={
                        "boo": ast.CTE(
                            name="boo",
                            expr=ast.Field(chain=["event"]),
                            cte_type="column",
                        )
                    },
                    select=[ast.Field(chain=["boo"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )
            self.assertEqual(
                self._select("with count() as kokku select kokku from events"),
                ast.SelectQuery(
                    ctes={
                        "kokku": ast.CTE(
                            name="kokku",
                            expr=ast.Call(name="count", args=[]),
                            cte_type="column",
                        )
                    },
                    select=[ast.Field(chain=["kokku"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_select_with_subqueries(self):
            self.assertEqual(
                self._select("with customers as (select 'yes' from events) select * from customers"),
                ast.SelectQuery(
                    ctes={
                        "customers": ast.CTE(
                            name="customers",
                            expr=ast.SelectQuery(
                                select=[ast.Constant(value="yes")],
                                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                            ),
                            cte_type="subquery",
                        )
                    },
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["customers"])),
                ),
            )

        def test_select_with_mixed(self):
            self.assertEqual(
                self._select("with happy as (select 'yes' from events), ':(' as sad select sad from happy"),
                ast.SelectQuery(
                    ctes={
                        "happy": ast.CTE(
                            name="happy",
                            expr=ast.SelectQuery(
                                select=[ast.Constant(value="yes")],
                                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                            ),
                            cte_type="subquery",
                        ),
                        "sad": ast.CTE(name="sad", expr=ast.Constant(value=":("), cte_type="column"),
                    },
                    select=[ast.Field(chain=["sad"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["happy"])),
                ),
            )

        def test_ctes_subquery_recursion(self):
            query = "with users as (select event, timestamp as tt from events ), final as ( select tt from users ) select * from final"
            self.assertEqual(
                self._select(query),
                ast.SelectQuery(
                    ctes={
                        "users": ast.CTE(
                            name="users",
                            expr=ast.SelectQuery(
                                select=[
                                    ast.Field(chain=["event"]),
                                    ast.Alias(alias="tt", expr=ast.Field(chain=["timestamp"])),
                                ],
                                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                            ),
                            cte_type="subquery",
                        ),
                        "final": ast.CTE(
                            name="final",
                            expr=ast.SelectQuery(
                                select=[ast.Field(chain=["tt"])],
                                select_from=ast.JoinExpr(table=ast.Field(chain=["users"])),
                            ),
                            cte_type="subquery",
                        ),
                    },
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["final"])),
                ),
            )

        def test_case_when(self):
            self.assertEqual(
                self._expr("case when 1 then 2 else 3 end"),
                ast.Call(
                    name="if",
                    args=[
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                        ast.Constant(value=3),
                    ],
                ),
            )

        def test_case_when_many(self):
            self.assertEqual(
                self._expr("case when 1 then 2 when 3 then 4 else 5 end"),
                ast.Call(
                    name="multiIf",
                    args=[
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                        ast.Constant(value=3),
                        ast.Constant(value=4),
                        ast.Constant(value=5),
                    ],
                ),
            )

        def test_case_when_case(self):
            self.assertEqual(
                self._expr("case 0 when 1 then 2 when 3 then 4 else 5 end"),
                ast.Call(
                    name="transform",
                    args=[
                        ast.Constant(value=0),
                        ast.Array(exprs=[ast.Constant(value=1), ast.Constant(value=3)]),
                        ast.Array(exprs=[ast.Constant(value=2), ast.Constant(value=4)]),
                        ast.Constant(value=5),
                    ],
                ),
            )

        def test_window_functions(self):
            query = "SELECT person.id, min(timestamp) over (PARTITION by person.id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS timestamp FROM events"
            expr = self._select(query)
            expected = ast.SelectQuery(
                select=[
                    ast.Field(chain=["person", "id"]),
                    ast.Alias(
                        alias="timestamp",
                        expr=ast.WindowFunction(
                            name="min",
                            exprs=[ast.Field(chain=["timestamp"])],
                            over_expr=ast.WindowExpr(
                                partition_by=[ast.Field(chain=["person", "id"])],
                                order_by=[
                                    ast.OrderExpr(
                                        expr=ast.Field(chain=["timestamp"]),
                                        order="DESC",
                                    )
                                ],
                                frame_method="ROWS",
                                frame_start=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=None),
                                frame_end=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=1),
                            ),
                        ),
                    ),
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            )
            self.assertEqual(expr, expected)

        def test_window_functions_call_arg(self):
            query = "SELECT quantiles(0.0, 0.25, 0.5, 0.75, 1.0)(distinct distinct_id) over () as values FROM events"
            expr = self._select(query)
            expected = ast.SelectQuery(
                select=[
                    ast.Alias(
                        alias="values",
                        expr=ast.WindowFunction(
                            name="quantiles",
                            args=[ast.Field(chain=["distinct_id"])],
                            exprs=[
                                ast.Constant(value=0.0),
                                ast.Constant(value=0.25),
                                ast.Constant(value=0.5),
                                ast.Constant(value=0.75),
                                ast.Constant(value=1.0),
                            ],
                            over_expr=ast.WindowExpr(),
                        ),
                        hidden=False,
                    )
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            )
            self.assertEqual(expr, expected)

        def test_window_functions_with_window(self):
            query = "SELECT person.id, min(timestamp) over win1 AS timestamp FROM events WINDOW win1 as (PARTITION by person.id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)"
            expr = self._select(query)
            expected = ast.SelectQuery(
                select=[
                    ast.Field(chain=["person", "id"]),
                    ast.Alias(
                        alias="timestamp",
                        expr=ast.WindowFunction(
                            name="min",
                            exprs=[ast.Field(chain=["timestamp"])],
                            over_identifier="win1",
                        ),
                    ),
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                window_exprs={
                    "win1": ast.WindowExpr(
                        partition_by=[ast.Field(chain=["person", "id"])],
                        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
                        frame_method="ROWS",
                        frame_start=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=None),
                        frame_end=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=1),
                    )
                },
            )
            self.assertEqual(expr, expected)

        def test_reserved_keyword_alias_error(self):
            query = f"SELECT 0 AS trUE FROM events"
            with self.assertRaisesMessage(
                SyntaxError,
                '"trUE" cannot be an alias or identifier, as it\'s a reserved keyword',
            ) as e:
                self._select(query)
            self.assertEqual(e.exception.start, 7)
            self.assertEqual(e.exception.end, 16)

        def test_malformed_sql(self):
            query = "SELEC 2"
            with self.assertRaisesMessage(
                SyntaxError,
                "mismatched input 'SELEC' expecting {SELECT, WITH, '{', '(', '<'}",
            ) as e:
                self._select(query)
            self.assertEqual(e.exception.start, 0)
            self.assertEqual(e.exception.end, 7)

        def test_visit_hogqlx_tag(self):
            node = self._select("select event from <HogQLQuery query='select event from events' />")
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(
                kind="HogQLQuery",
                attributes=[ast.HogQLXAttribute(name="query", value=ast.Constant(value="select event from events"))],
            )

            node2 = self._select("select event from (<HogQLQuery query='select event from events' />)")
            assert node2 == node

        def test_visit_hogqlx_tag_nested(self):
            # Basic case
            node = self._select(
                "select event from <OuterQuery><HogQLQuery query='select event from events' /></OuterQuery>"
            )
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(
                kind="OuterQuery",
                attributes=[
                    ast.HogQLXAttribute(
                        name="children",
                        value=[
                            ast.HogQLXTag(
                                kind="HogQLQuery",
                                attributes=[
                                    ast.HogQLXAttribute(
                                        name="query", value=ast.Constant(value="select event from events")
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )

            # Empty tag
            node = self._select("select event from <OuterQuery></OuterQuery>")
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(kind="OuterQuery", attributes=[])

            # With attribute
            node = self._select(
                "select event from <OuterQuery q='b'><HogQLQuery query='select event from events' /></OuterQuery>"
            )
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(
                kind="OuterQuery",
                attributes=[
                    ast.HogQLXAttribute(name="q", value=ast.Constant(value="b")),
                    ast.HogQLXAttribute(
                        name="children",
                        value=[
                            ast.HogQLXTag(
                                kind="HogQLQuery",
                                attributes=[
                                    ast.HogQLXAttribute(
                                        name="query", value=ast.Constant(value="select event from events")
                                    )
                                ],
                            )
                        ],
                    ),
                ],
            )

            # With mismatched closing tag
            with self.assertRaises(ExposedHogQLError) as e:
                self._select(
                    "select event from <OuterQuery q='b'><HogQLQuery query='select event from events' /></HogQLQuery>"
                )
            assert str(e.exception) == "Opening and closing HogQLX tags must match. Got OuterQuery and HogQLQuery"

            # With mismatched closing tag
            with self.assertRaises(ExposedHogQLError) as e:
                self._select(
                    "select event from <OuterQuery children='b'><HogQLQuery query='select event from events' /></OuterQuery>"
                )
            assert str(e.exception) == "Can't have a HogQLX tag with both children and a 'children' attribute"

        def test_visit_hogqlx_tag_alias(self):
            node = self._select("select event from <HogQLQuery query='select event from events' /> as a")
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            alias = node.select_from.alias
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(
                kind="HogQLQuery",
                attributes=[ast.HogQLXAttribute(name="query", value=ast.Constant(value="select event from events"))],
            )
            assert alias == "a"

            node2 = self._select("select event from <HogQLQuery query='select event from events' /> a")
            assert node2 == node

        def test_visit_hogqlx_tag_source(self):
            query = """
                select id, email from (
                    <ActorsQuery
                        select={['id', 'properties.email as email']}
                        source={
                            <HogQLQuery query='select distinct person_id from events' />
                        }
                    />
                )
            """
            node = self._select(query)
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(
                kind="ActorsQuery",
                attributes=[
                    ast.HogQLXAttribute(
                        name="select",
                        value=ast.Array(
                            exprs=[ast.Constant(value="id"), ast.Constant(value="properties.email as email")]
                        ),
                    ),
                    ast.HogQLXAttribute(
                        name="source",
                        value=ast.HogQLXTag(
                            kind="HogQLQuery",
                            attributes=[
                                ast.HogQLXAttribute(
                                    name="query", value=ast.Constant(value="select distinct person_id from events")
                                )
                            ],
                        ),
                    ),
                ],
            )

        def test_visit_hogqlx_tag_column_source(self):
            query = """
                select <a href='https://google.com'>{event}</a> from events
            """
            node = self._select(query)
            assert isinstance(node, ast.SelectQuery) and cast(ast.HogQLXTag, node.select[0]) == ast.HogQLXTag(
                kind="a",
                attributes=[
                    ast.HogQLXAttribute(name="href", value=Constant(value="https://google.com")),
                    ast.HogQLXAttribute(name="children", value=[ast.Field(chain=["event"])]),
                ],
            )

        def test_visit_hogqlx_multiple_children(self):
            query = """
                select <a href='https://google.com'>{event}<b>{'Bold!'}</b></a> from events
            """
            node = self._select(query)
            assert isinstance(node, ast.SelectQuery) and cast(ast.HogQLXTag, node.select[0]) == ast.HogQLXTag(
                kind="a",
                attributes=[
                    ast.HogQLXAttribute(name="href", value=Constant(value="https://google.com")),
                    ast.HogQLXAttribute(
                        name="children",
                        value=[
                            ast.Field(chain=["event"]),
                            ast.HogQLXTag(
                                kind="b",
                                attributes=[
                                    ast.HogQLXAttribute(name="children", value=[ast.Constant(value="Bold!")]),
                                ],
                            ),
                        ],
                    ),
                ],
            )

        def test_visit_hogqlx_text_only_child(self):
            """A tag with a single plain-text child should be turned into
            a Constant wrapped in the auto-injected `children` attribute."""
            node = self._select("select <span>Hello World</span> from events")
            assert isinstance(node, ast.SelectQuery)
            tag = cast(ast.HogQLXTag, node.select[0])
            self.assertEqual(
                tag,
                ast.HogQLXTag(
                    kind="span",
                    attributes=[
                        ast.HogQLXAttribute(
                            name="children",
                            value=[ast.Constant(value="Hello World")],
                        )
                    ],
                ),
            )

        def test_visit_hogqlx_text_and_expr_children(self):
            """Mixed text + expression children must keep ordering:
            Constant('Hello')  →  Field(event)."""
            node = self._select("select <span>Hello {event}</span> from events")
            assert isinstance(node, ast.SelectQuery)
            tag = cast(ast.HogQLXTag, node.select[0])
            self.assertEqual(
                tag,
                ast.HogQLXTag(
                    kind="span",
                    attributes=[
                        ast.HogQLXAttribute(
                            name="children",
                            value=[
                                ast.Constant(value="Hello "),
                                ast.Field(chain=["event"]),
                            ],
                        )
                    ],
                ),
            )

        # 1. <strong>hello world <strong>banana</strong></strong>
        def test_visit_hogqlx_nested_tags(self) -> None:
            node = self._select("select <strong>hello world <strong>banana</strong></strong>")
            assert isinstance(node, ast.SelectQuery)
            tag = cast(ast.HogQLXTag, node.select[0])

            self.assertEqual(
                tag,
                ast.HogQLXTag(
                    kind="strong",
                    attributes=[
                        ast.HogQLXAttribute(
                            name="children",
                            value=[
                                ast.Constant(value="hello world "),
                                ast.HogQLXTag(
                                    kind="strong",
                                    attributes=[
                                        ast.HogQLXAttribute(
                                            name="children",
                                            value=[ast.Constant(value="banana")],
                                        )
                                    ],
                                ),
                            ],
                        )
                    ],
                ),
            )

        # 2. <em />
        def test_visit_hogqlx_self_closing(self) -> None:
            node = self._select("select <em /> from events")
            assert isinstance(node, ast.SelectQuery)
            tag = cast(ast.HogQLXTag, node.select[0])

            # A self-closing element has no “children” attribute at all.
            self.assertEqual(tag, ast.HogQLXTag(kind="em", attributes=[]))

        # 3. <strong>{event} <em>asd</em></strong>
        def test_visit_hogqlx_expr_text_and_tag_children(self) -> None:
            node = self._select("select <strong>{event} <em>asd</em></strong> from events")
            assert isinstance(node, ast.SelectQuery)
            tag = cast(ast.HogQLXTag, node.select[0])

            self.assertEqual(
                tag,
                ast.HogQLXTag(
                    kind="strong",
                    attributes=[
                        ast.HogQLXAttribute(
                            name="children",
                            value=[
                                ast.Field(chain=["event"]),
                                ast.Constant(value=" "),
                                ast.HogQLXTag(
                                    kind="em",
                                    attributes=[
                                        ast.HogQLXAttribute(
                                            name="children",
                                            value=[ast.Constant(value="asd")],
                                        )
                                    ],
                                ),
                            ],
                        )
                    ],
                ),
            )

        # 4. <strong><a href="…">Hello <em>{event}</em></a>{'a'}</strong>
        def test_visit_hogqlx_mixed_nested_attributes(self) -> None:
            node = self._select(
                "select <strong>"
                "<a href='https://google.com'>Hello <em>{event}</em></a>"
                "{'a'}"
                "</strong> from events"
            )
            assert isinstance(node, ast.SelectQuery)
            outer = cast(ast.HogQLXTag, node.select[0])

            expected = ast.HogQLXTag(
                kind="strong",
                attributes=[
                    ast.HogQLXAttribute(
                        name="children",
                        value=[
                            ast.HogQLXTag(
                                kind="a",
                                attributes=[
                                    ast.HogQLXAttribute(
                                        name="href",
                                        value=ast.Constant(value="https://google.com"),
                                    ),
                                    ast.HogQLXAttribute(
                                        name="children",
                                        value=[
                                            ast.Constant(value="Hello "),
                                            ast.HogQLXTag(
                                                kind="em",
                                                attributes=[
                                                    ast.HogQLXAttribute(
                                                        name="children",
                                                        value=[ast.Field(chain=["event"])],
                                                    )
                                                ],
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            ast.Constant(value="a"),
                        ],
                    )
                ],
            )

            self.assertEqual(outer, expected)

        # Regression tests: “<” operator vs HOGQLX-tag opener
        def test_lt_vs_tags_and_comments(self):
            # 1. Plain operator – no whitespace
            self.assertEqual(
                self._expr("a<b"),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["a"]),
                    right=ast.Field(chain=["b"]),
                ),
            )

            # 2. Operator with unusual spacing: the ‘b+c’ part must be parsed first,
            #    so we use a small arithmetic expression on the RHS.
            self.assertEqual(
                self._expr("a <b +c"),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["a"]),
                    right=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Add,
                        left=ast.Field(chain=["b"]),
                        right=ast.Field(chain=["c"]),
                    ),
                ),
            )

            # 3. Trailing whitespace after RHS – still an operator
            self.assertEqual(
                self._expr("a < timestamp "),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["a"]),
                    right=ast.Field(chain=["timestamp"]),
                ),
            )

            # 4. Same, but with an end-of-line comment that must be ignored
            self.assertEqual(
                self._expr("a < timestamp // comment\n"),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["a"]),
                    right=ast.Field(chain=["timestamp"]),
                ),
            )

            # 5. Sequence that *is* a tag: `<b …`  → should now fail to parse
            with self.assertRaises(SyntaxError):
                self._expr("a <b c")

        def test_program_while_lt_with_space_and_comment(self):
            code = """
                while (a < timestamp // comment
                ) {
                    let c := 3;
                }
            """
            program = self._program(code)
            expected = Program(
                declarations=[
                    WhileStatement(
                        expr=CompareOperation(
                            op=CompareOperationOp.Lt,
                            left=Field(chain=["a"]),
                            right=Field(chain=["timestamp"]),
                        ),
                        body=Block(
                            declarations=[
                                VariableDeclaration(
                                    name="c",
                                    expr=Constant(value=3),
                                )
                            ],
                        ),
                    )
                ],
            )
            self.assertEqual(program, expected)

        def test_select_extract_as_function(self):
            node = self._select("select extract('string', 'other string') from events")

            assert node == ast.SelectQuery(
                select=[
                    ast.Call(
                        name="extract",
                        args=[ast.Constant(value="string"), ast.Constant(value="other string")],
                    )
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            )

        def test_trim_leading_trailing_both(self):
            node1 = self._select(
                "select trim(LEADING 'fish' FROM event), trim(TRAILING 'fish' FROM event), trim(BOTH 'fish' FROM event) from events"
            )
            node2 = self._select(
                "select trimLeft(event, 'fish'), trimRight(event, 'fish'), trim(event, 'fish') from events"
            )
            assert node1 == node2

            node3 = self._select(
                "select TRIM (LEADING 'fish' FROM event), TRIM (TRAILING 'fish' FROM event), TRIM (BOTH 'fish' FROM event) from events"
            )
            assert node3 == node1

            node4 = self._select("select TRIM (LEADING f'fi{'a'}sh' FROM event) from events")
            assert isinstance(node4, ast.SelectQuery)
            assert node4.select[0] == ast.Call(
                name="trimLeft",
                args=[
                    ast.Field(chain=["event"]),
                    ast.Call(
                        name="concat",
                        args=[
                            ast.Constant(value="fi"),
                            ast.Constant(value="a"),
                            ast.Constant(value="sh"),
                        ],
                    ),
                ],
            )

        def test_template_strings(self):
            node = self._expr("f'hello {event}'")
            assert node == ast.Call(name="concat", args=[ast.Constant(value="hello "), ast.Field(chain=["event"])])

            select = self._select("select f'hello {event}' from events")
            assert isinstance(select, ast.SelectQuery)
            assert select.select[0] == node

        def test_template_strings_nested_strings(self):
            node = self._expr("a = f'aa {1 + call('string')}aa'")
            assert node == ast.CompareOperation(
                left=ast.Field(chain=["a"]),
                right=ast.Call(
                    name="concat",
                    args=[
                        ast.Constant(value="aa "),
                        ast.ArithmeticOperation(
                            left=ast.Constant(value=1),
                            right=ast.Call(name="call", args=[ast.Constant(value="string")]),
                            op=ast.ArithmeticOperationOp.Add,
                        ),
                        ast.Constant(value="aa"),
                    ],
                ),
                op=ast.CompareOperationOp.Eq,
            )

        def test_template_strings_multiple_levels(self):
            node = self._expr("a = f'aa {1 + call(f'fi{one(more, time, 'stringy')}sh')}aa'")
            assert node == ast.CompareOperation(
                left=ast.Field(chain=["a"]),
                right=ast.Call(
                    name="concat",
                    args=[
                        ast.Constant(value="aa "),
                        ast.ArithmeticOperation(
                            left=ast.Constant(value=1),
                            right=ast.Call(
                                name="call",
                                args=[
                                    ast.Call(
                                        name="concat",
                                        args=[
                                            ast.Constant(value="fi"),
                                            ast.Call(
                                                name="one",
                                                args=[
                                                    ast.Field(chain=["more"]),
                                                    ast.Field(chain=["time"]),
                                                    ast.Constant(value="stringy"),
                                                ],
                                            ),
                                            ast.Constant(value="sh"),
                                        ],
                                    )
                                ],
                            ),
                            op=ast.ArithmeticOperationOp.Add,
                        ),
                        ast.Constant(value="aa"),
                    ],
                ),
                op=ast.CompareOperationOp.Eq,
            )

        def test_template_strings_full(self):
            node = self._string_template("hello {event}")
            assert node == ast.Call(name="concat", args=[ast.Constant(value="hello "), ast.Field(chain=["event"])])

            node = self._string_template("we're ready to open {person.properties.email}")
            assert node == ast.Call(
                name="concat",
                args=[ast.Constant(value="we're ready to open "), ast.Field(chain=["person", "properties", "email"])],
            )

            node = self._string_template("strings' to {'strings'}")
            assert node == ast.Call(
                name="concat", args=[ast.Constant(value="strings' to "), ast.Constant(value="strings")]
            )
            node2 = self._expr("f'strings\\' to {'strings'}'")
            assert node2 == node

            node = self._string_template("strings\\{ to {'strings'}")
            assert node == ast.Call(
                name="concat", args=[ast.Constant(value="strings{ to "), ast.Constant(value="strings")]
            )
            node2 = self._expr("f'strings\\{ to {'strings'}'")
            assert node2 == node

        def test_template_strings_full_multiline(self):
            node = self._string_template("hello \n{event}")
            assert node == ast.Call(name="concat", args=[ast.Constant(value="hello \n"), ast.Field(chain=["event"])])

            node = self._string_template("we're ready to \n\nopen {\nperson.properties.email\n}")
            assert node == ast.Call(
                name="concat",
                args=[
                    ast.Constant(value="we're ready to \n\nopen "),
                    ast.Field(chain=["person", "properties", "email"]),
                ],
            )

        def test_program_variable_declarations(self):
            code = "let a := '123'; let b := a - 2; print(b);"
            program = self._program(code)

            expected = Program(
                declarations=[
                    VariableDeclaration(name="a", expr=Constant(type=None, value="123")),
                    VariableDeclaration(
                        name="b",
                        expr=ArithmeticOperation(
                            type=None,
                            left=Field(type=None, chain=["a"]),
                            right=Constant(type=None, value=2),
                            op=ArithmeticOperationOp.Sub,
                        ),
                    ),
                    ExprStatement(
                        expr=Call(
                            type=None,
                            name="print",
                            args=[Field(type=None, chain=["b"])],
                            params=None,
                            distinct=False,
                        ),
                    ),
                ]
            )
            self.assertEqual(program, expected)

        def test_program_variable_reassignment(self):
            code = "let a := 3; a := 4;"
            program = self._program(code)
            expected = Program(
                start=None,
                end=None,
                declarations=[
                    VariableDeclaration(
                        start=None,
                        end=None,
                        name="a",
                        expr=Constant(start=None, end=None, type=None, value=3),
                    ),
                    VariableAssignment(
                        start=None,
                        end=None,
                        left=Field(chain=["a"]),
                        right=Constant(start=None, end=None, type=None, value=4),
                    ),
                ],
            )
            self.assertEqual(program, expected)

        def test_program_variable_declarations_with_sql_expr(self):
            code = """
                let query := (select id, properties.email from events where timestamp > now() - interval 1 day);
                let results := run(query);
            """
            program = self._program(code)
            expected = Program(
                declarations=[
                    VariableDeclaration(
                        name="query",
                        expr=SelectQuery(
                            type=None,
                            ctes=None,
                            select=[
                                Field(type=None, chain=["id"]),
                                Field(type=None, chain=["properties", "email"]),
                            ],
                            distinct=None,
                            select_from=JoinExpr(
                                type=None,
                                join_type=None,
                                table=Field(type=None, chain=["events"]),
                                table_args=None,
                                alias=None,
                                table_final=None,
                                constraint=None,
                                next_join=None,
                                sample=None,
                            ),
                            array_join_op=None,
                            array_join_list=None,
                            window_exprs=None,
                            where=CompareOperation(
                                type=None,
                                left=Field(type=None, chain=["timestamp"]),
                                right=ArithmeticOperation(
                                    type=None,
                                    left=Call(type=None, name="now", args=[], params=None, distinct=False),
                                    right=Call(
                                        type=None,
                                        name="toIntervalDay",
                                        args=[Constant(type=None, value=1)],
                                        params=None,
                                        distinct=False,
                                    ),
                                    op=ArithmeticOperationOp.Sub,
                                ),
                                op=CompareOperationOp.Gt,
                            ),
                            prewhere=None,
                            having=None,
                            group_by=None,
                            order_by=None,
                            limit=None,
                            limit_by=None,
                            limit_with_ties=None,
                            offset=None,
                            settings=None,
                            view_name=None,
                        ),
                    ),
                    VariableDeclaration(
                        name="results",
                        expr=Call(
                            name="run",
                            args=[Field(type=None, chain=["query"])],
                            params=None,
                            distinct=False,
                        ),
                    ),
                ]
            )
            self.assertEqual(program, expected)

        def test_program_if(self):
            code = """
                if (a) {
                    let c := 3;
                }
                else
                    print(d);
            """

            program = self._program(code)
            expected = Program(
                declarations=[
                    IfStatement(
                        expr=Field(type=None, chain=["a"]),
                        then=Block(
                            declarations=[
                                VariableDeclaration(
                                    name="c",
                                    expr=Constant(type=None, value=3),
                                )
                            ],
                        ),
                        else_=ExprStatement(
                            expr=Call(
                                type=None,
                                name="print",
                                args=[Field(type=None, chain=["d"])],
                                params=None,
                                distinct=False,
                            ),
                        ),
                    )
                ],
            )

            self.assertEqual(program, expected)

        def test_program_while(self):
            code = """
                while (a < 5) {
                    let c := 3;
                }
            """

            program = self._program(code)
            expected = Program(
                declarations=[
                    WhileStatement(
                        expr=CompareOperation(
                            type=None,
                            left=Field(type=None, chain=["a"]),
                            right=Constant(type=None, value=5),
                            op=CompareOperationOp.Lt,
                        ),
                        body=Block(
                            declarations=[VariableDeclaration(name="c", expr=Constant(type=None, value=3))],
                        ),
                    )
                ],
            )

            self.assertEqual(program, expected)

        def test_program_function(self):
            code = """
                fun query(a, b) {
                    let c := 3;
                }
            """

            program = self._program(code)
            expected = Program(
                declarations=[
                    Function(
                        name="query",
                        params=["a", "b"],
                        body=Block(
                            declarations=[VariableDeclaration(name="c", expr=Constant(type=None, value=3))],
                        ),
                    )
                ],
            )
            self.assertEqual(program, expected)

        def test_program_functions(self):
            # test both "fn" (deprecated) and "fun"
            code = """
                fn query(a, b) {
                    let c := 3;
                }

                fun read(a, b) {
                    print(3);
                    let b := 4;
                }
            """

            program = self._program(code)

            expected = Program(
                start=None,
                end=None,
                declarations=[
                    Function(
                        start=None,
                        end=None,
                        name="query",
                        params=["a", "b"],
                        body=Block(
                            start=None,
                            end=None,
                            declarations=[
                                VariableDeclaration(
                                    start=None,
                                    end=None,
                                    name="c",
                                    expr=Constant(start=None, end=None, type=None, value=3),
                                )
                            ],
                        ),
                    ),
                    Function(
                        start=None,
                        end=None,
                        name="read",
                        params=["a", "b"],
                        body=Block(
                            start=None,
                            end=None,
                            declarations=[
                                ExprStatement(
                                    start=None,
                                    end=None,
                                    expr=Call(
                                        start=None,
                                        end=None,
                                        type=None,
                                        name="print",
                                        args=[Constant(start=None, end=None, type=None, value=3)],
                                        params=None,
                                        distinct=False,
                                    ),
                                ),
                                VariableDeclaration(
                                    start=None,
                                    end=None,
                                    name="b",
                                    expr=Constant(start=None, end=None, type=None, value=4),
                                ),
                            ],
                        ),
                    ),
                ],
            )
            self.assertEqual(program, expected)

        def test_program_array(self):
            code = "let a := [1, 2, 3];"
            program = self._program(code)

            expected = Program(
                start=None,
                end=None,
                declarations=[
                    VariableDeclaration(
                        start=None,
                        end=None,
                        name="a",
                        expr=Array(
                            start=None,
                            end=None,
                            type=None,
                            exprs=[
                                Constant(start=None, end=None, type=None, value=1),
                                Constant(start=None, end=None, type=None, value=2),
                                Constant(start=None, end=None, type=None, value=3),
                            ],
                        ),
                    )
                ],
            )
            self.assertEqual(program, expected)

        def test_program_dict(self):
            code = "let a := {};"
            program = self._program(code)

            expected = Program(
                start=None,
                end=None,
                declarations=[
                    VariableDeclaration(
                        start=None,
                        end=None,
                        name="a",
                        expr=Dict(start=None, end=None, type=None, items=[]),
                    )
                ],
            )

            self.assertEqual(program, expected)

            code = "let a := {1: 2, 'a': [3, 4], g: true};"
            program = self._program(code)

            expected = Program(
                start=None,
                end=None,
                declarations=[
                    VariableDeclaration(
                        start=None,
                        end=None,
                        name="a",
                        expr=Dict(
                            start=None,
                            end=None,
                            type=None,
                            items=[
                                (
                                    Constant(start=None, end=None, type=None, value=1),
                                    Constant(start=None, end=None, type=None, value=2),
                                ),
                                (
                                    Constant(start=None, end=None, type=None, value="a"),
                                    Array(
                                        start=None,
                                        end=None,
                                        type=None,
                                        exprs=[
                                            Constant(start=None, end=None, type=None, value=3),
                                            Constant(start=None, end=None, type=None, value=4),
                                        ],
                                    ),
                                ),
                                (
                                    Field(start=None, end=None, type=None, chain=["g"]),
                                    Constant(start=None, end=None, type=None, value=True),
                                ),
                            ],
                        ),
                    )
                ],
            )
            self.assertEqual(program, expected)

        def test_program_simple_return(self):
            code = "return"
            program = self._program(code)
            expected = Program(
                declarations=[ast.ReturnStatement(expr=None)],
            )
            self.assertEqual(program, expected)

        def test_program_simple_return_twice(self):
            code = "return;return"
            program = self._program(code)
            expected = Program(
                declarations=[ast.ReturnStatement(expr=None), ast.ReturnStatement(expr=None)],
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_throw_simple(self):
            code = "return"
            program = self._program(code)
            expected = Program(
                declarations=[ast.ReturnStatement(expr=None)],
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_catch_blocks(self):
            code = "try { 1 } catch (e) { 2 }"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[("e", None, ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))]))],
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_finally_simple(self):
            code = "try {1 } finally { 2 }"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[],
                        finally_stmt=ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))]),
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_catch_finally(self):
            code = "try {1} catch (e) {2} finally {3}"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[("e", None, ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))]))],
                        finally_stmt=ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=3))]),
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_alone(self):
            # This parses, but will throw later when printing bytecode.
            code = "try {1}"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]), catches=[]
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_catch_type(self):
            code = "try {1} catch (e: DodgyError) {2}"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[
                            ("e", "DodgyError", ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))]))
                        ],
                        finally_stmt=None,
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_catch_multiple(self):
            code = "try {1} catch (e: DodgyError) {2}  catch (e: FishyError) {3}"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[
                            ("e", "DodgyError", ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))])),
                            ("e", "FishyError", ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=3))])),
                        ],
                        finally_stmt=None,
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_catch_multiple_plain(self):
            code = "try {1} catch (e: DodgyError) {2}  catch (e: FishyError) {3} catch {4}"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[
                            ("e", "DodgyError", ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))])),
                            ("e", "FishyError", ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=3))])),
                            (None, None, ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=4))])),
                        ],
                        finally_stmt=None,
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_pop_empty_stack(self):
            with self.assertRaises(SyntaxError) as e:
                self._select("select } from events")
            self.assertEqual(str(e.exception), "Unmatched curly bracket")

        def test_for_in_loops(self):
            code = """
                for (let i in [1, 2, 3]) {
                    print(a);
                }
            """
            program = self._program(code)
            expected = ast.Program(
                declarations=[
                    ast.ForInStatement(
                        keyVar=None,
                        valueVar="i",
                        expr=ast.Array(exprs=[Constant(value=1), Constant(value=2), Constant(value=3)]),
                        body=ast.Block(
                            declarations=[ast.ExprStatement(expr=Call(name="print", args=[Field(chain=["a"])]))]
                        ),
                    )
                ]
            )
            self.assertEqual(program, expected)

            code = """
                for (let key, value in [1, 2, 3]) {
                    print(a);
                }
            """
            program = self._program(code)
            expected = ast.Program(
                declarations=[
                    ast.ForInStatement(
                        keyVar="key",
                        valueVar="value",
                        expr=ast.Array(exprs=[Constant(value=1), Constant(value=2), Constant(value=3)]),
                        body=ast.Block(
                            declarations=[ast.ExprStatement(expr=Call(name="print", args=[Field(chain=["a"])]))]
                        ),
                    )
                ]
            )
            self.assertEqual(program, expected)

    return TestParser
