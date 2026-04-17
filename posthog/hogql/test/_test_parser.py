import math
from typing import Optional, cast

from posthog.test.base import BaseTest, MemoryLeakTestMixin

from parameterized import parameterized

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
from posthog.hogql.constants import HogQLParserBackend
from posthog.hogql.errors import ExposedHogQLError, SyntaxError
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_program, parse_select, parse_string_template
from posthog.hogql.visitor import clear_locations


def parser_test_factory(backend: HogQLParserBackend):
    base_classes = (BaseTest,) if backend == "python" else (MemoryLeakTestMixin, BaseTest)

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
            self.assertEqual(
                self._expr("arr[1:3]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=ast.Constant(value=1),
                    end_expr=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._expr("arr[:3]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=None,
                    end_expr=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._expr("arr[1:]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=ast.Constant(value=1),
                    end_expr=None,
                ),
            )
            self.assertEqual(
                self._expr("arr[:]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=None,
                    end_expr=None,
                ),
            )
            self.assertEqual(
                self._expr("arr[(1 + 2):(-3)]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Add,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                    end_expr=ast.Constant(value=-3),
                ),
            )
            self.assertEqual(
                self._expr("arr[-5:]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=ast.Constant(value=-5),
                    end_expr=None,
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
                self._expr("lambda x: x * 2"),
                ast.Lambda(
                    args=["x"],
                    expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Mult,
                        left=ast.Field(chain=["x"]),
                        right=ast.Constant(value=2),
                    ),
                ),
            )
            self.assertEqual(
                self._expr("lambda x, y: x * y"),
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

        def test_try_cast(self):
            self.assertEqual(
                self._expr("try_cast(1 AS Int64)"),
                ast.TryCast(expr=ast.Constant(value=1), type_name="int64"),
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
            self.assertEqual(self._expr("'\\x41'"), ast.Constant(value="\\x41"))
            self.assertEqual(self._expr("'\\x61\\x62'"), ast.Constant(value="\\x61\\x62"))
            self.assertEqual(self._expr("'\\x5a'"), ast.Constant(value="\\x5a"))

            # String literals containing special float names should remain as strings
            self.assertEqual(self._expr("'Infinity'"), ast.Constant(value="Infinity"))
            self.assertEqual(self._expr("'-Infinity'"), ast.Constant(value="-Infinity"))
            self.assertEqual(self._expr("'NaN'"), ast.Constant(value="NaN"))

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
            self.assertEqual(
                self._expr("1 is distinct from 2"),
                ast.IsDistinctFrom(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    negated=False,
                ),
            )
            self.assertEqual(
                self._expr("1 is not distinct from 2"),
                ast.IsDistinctFrom(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    negated=True,
                ),
            )

        def test_null_comparison_operations(self):
            self.assertEqual(
                self._expr("1 is null"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=None),
                    op=ast.CompareOperationOp.Eq,
                    is_null_comparison_style=True,
                ),
            )
            self.assertEqual(
                self._expr("1 is not null"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=None),
                    op=ast.CompareOperationOp.NotEq,
                    is_null_comparison_style=True,
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

        @parameterized.expand([["percentile_cont"], ["percentile_disc"]])
        def test_percentile_calls_within_group(self, function_name: str):
            self.assertEqual(
                self._expr(f"{function_name}(0.5) within group (order by foo desc)"),
                ast.Call(
                    name=function_name,
                    args=[],
                    params=[ast.Constant(value=0.5)],
                    within_group=[ast.OrderExpr(expr=ast.Field(chain=["foo"]), order="DESC")],
                ),
            )

        def test_function_calls_with_filter(self):
            self.assertEqual(
                self._expr("sum(event) FILTER (WHERE event = 'a')"),
                ast.Call(
                    name="sum",
                    params=None,
                    args=[ast.Field(chain=["event"])],
                    distinct=False,
                    filter_expr=ast.CompareOperation(
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value="a"),
                        op=ast.CompareOperationOp.Eq,
                    ),
                ),
            )

        def test_function_calls_with_order_by(self):
            self.assertEqual(
                self._expr("sum(event ORDER BY timestamp DESC)"),
                ast.Call(
                    name="sum",
                    params=None,
                    args=[ast.Field(chain=["event"])],
                    distinct=False,
                    order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
                ),
            )

        def test_keyword_named_function_call(self):
            self.assertEqual(
                self._expr("if(1, 2, 3)"),
                ast.Call(
                    name="if",
                    params=None,
                    args=[
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                        ast.Constant(value=3),
                    ],
                    distinct=False,
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

        def test_quoted_reserved_keyword_alias(self):
            self.assertEqual(
                self._select('select 1 "from"'),
                ast.SelectQuery(
                    select=[ast.Alias(alias="from", expr=ast.Constant(value=1))],
                ),
            )

        def test_quoted_reserved_keyword_alias_with_from_clause(self):
            self.assertEqual(
                self._select('select 1 "from" from events'),
                ast.SelectQuery(
                    select=[ast.Alias(alias="from", expr=ast.Constant(value=1))],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_not_expression_is_not_parsed_as_implicit_alias(self):
            self.assertEqual(
                self._select("select not true"),
                ast.SelectQuery(
                    select=[ast.Not(expr=ast.Constant(value=True))],
                ),
            )

        @parameterized.expand(
            [["ascending"], ["cohort"], ["date"], ["descending"], ["final"], ["id"], ["return"], ["top"], ["totals"]]
        )
        def test_allowed_keyword_implicit_aliases(self, alias: str):
            self.assertEqual(
                self._select(f"select 1 {alias} from events"),
                ast.SelectQuery(
                    select=[ast.Alias(alias=alias, expr=ast.Constant(value=1))],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        @parameterized.expand([["name"], ["timestamp"]])
        def test_disallowed_keyword_implicit_aliases(self, alias: str):
            with self.assertRaises(SyntaxError):
                self._select(f"select 1 {alias} from events")

        def test_from_cannot_precede_implicit_alias(self):
            with self.assertRaises(ExposedHogQLError):
                self._select("select from foo")

        def test_select_trailing_comma_before_from(self):
            self.assertEqual(
                self._select(
                    """
                    select
                      session.id as session_id,
                    from events
                    where
                      session_id = '019d4492-db9b-713e-b5ba-211e88348587'
                      and timestamp >= '1970-01-01'
                    """
                ),
                ast.SelectQuery(
                    select=[ast.Alias(alias="session_id", expr=ast.Field(chain=["session", "id"]))],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    where=ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["session_id"]),
                                right=ast.Constant(value="019d4492-db9b-713e-b5ba-211e88348587"),
                                op=ast.CompareOperationOp.Eq,
                            ),
                            ast.CompareOperation(
                                left=ast.Field(chain=["timestamp"]),
                                right=ast.Constant(value="1970-01-01"),
                                op=ast.CompareOperationOp.GtEq,
                            ),
                        ]
                    ),
                ),
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
                self._select("select total: 1 + 2"),
                ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="total",
                            expr=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Add,
                                left=ast.Constant(value=1),
                                right=ast.Constant(value=2),
                            ),
                        )
                    ]
                ),
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

        def test_select_qualify(self):
            self.assertEqual(
                self._select("select 1 qualify true"),
                ast.SelectQuery(select=[ast.Constant(value=1)], qualify=ast.Constant(value=True)),
            )
            self.assertEqual(
                self._select("select 1 qualify 1 == 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    qualify=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                ),
            )

        def test_select_qualify_with_having(self):
            self.assertEqual(
                self._select("select 1 having true qualify 1 == 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    having=ast.Constant(value=True),
                    qualify=ast.CompareOperation(
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
                self._select("select 1 from events as e (event_alias, ts_alias)"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        alias="e",
                        column_aliases=["event_alias", "ts_alias"],
                    ),
                ),
            )
            self.assertEqual(
                self._select("select * exclude (first_name) from customers"),
                ast.SelectQuery(
                    select=[ast.ColumnsExpr(all_columns=True, exclude=["first_name"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["customers"])),
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

        def test_select_replace_columns(self):
            self.assertEqual(
                self._select("select (* replace (1 as event)) from events"),
                ast.SelectQuery(
                    select=[ast.ColumnsExpr(all_columns=True, replace={"event": ast.Constant(value=1)})],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_ignore_nulls_expr(self):
            self.assertEqual(
                self._expr("event IGNORE NULLS"),
                ast.Field(chain=["event"]),
            )
            self.assertEqual(
                self._select("select event IGNORE NULLS from events"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["event"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_select_columns_qualified(self):
            self.assertEqual(
                self._select("select COLUMNS(events.*) from events"),
                ast.SelectQuery(
                    select=[ast.ColumnsExpr(columns=[ast.Field(chain=["events", "*"])])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )
            self.assertEqual(
                self._select("select COLUMNS(events.* EXCLUDE (event)) from events"),
                ast.SelectQuery(
                    select=[ast.ColumnsExpr(columns=[ast.ColumnsExpr(all_columns=True, exclude=["event"])])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )
            self.assertEqual(
                self._select("select COLUMNS(events.* REPLACE (1 as event)) from events"),
                ast.SelectQuery(
                    select=[ast.ColumnsExpr(all_columns=True, replace={"event": ast.Constant(value=1)})],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )
            self.assertEqual(
                self._select("select COLUMNS(events.* EXCLUDE (event) REPLACE (1 as event)) from events"),
                ast.SelectQuery(
                    select=[
                        ast.ColumnsExpr(
                            all_columns=True,
                            exclude=["event"],
                            replace={"event": ast.Constant(value=1)},
                        )
                    ],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
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

        def test_select_from_table_function_join(self):
            # Regression: TableFunctionExpr produced a JoinExpr without next_join,
            # causing chainJoinExprs to throw "JoinExpr is missing 'next_join' field"
            self.assertEqual(
                self._select("select 1 from numbers(10) JOIN events ON 1"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["numbers"]),
                        table_args=[ast.Constant(value=10)],
                        next_join=ast.JoinExpr(
                            join_type="JOIN",
                            table=ast.Field(chain=["events"]),
                            constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from numbers(10) CROSS JOIN events"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["numbers"]),
                        table_args=[ast.Constant(value=10)],
                        next_join=ast.JoinExpr(
                            join_type="CROSS JOIN",
                            table=ast.Field(chain=["events"]),
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

        def test_select_group_by_all(self):
            self.assertEqual(
                self._select("select distinct_id, event, count(*) from events GROUP BY ALL"),
                ast.SelectQuery(
                    select=[
                        ast.Field(chain=["distinct_id"]),
                        ast.Field(chain=["event"]),
                        ast.Call(name="count", args=[ast.Field(chain=["*"])]),
                    ],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    group_by=None,
                    group_by_mode="all",
                ),
            )

        @parameterized.expand(
            [
                (
                    "count_cast_with_as",
                    "select count(*)::int as num_events from active_events",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="num_events",
                                expr=ast.TypeCast(
                                    expr=ast.Call(name="count", args=[ast.Field(chain=["*"])]),
                                    type_name="int",
                                ),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["active_events"])),
                    ),
                ),
                (
                    "paren_count_cast_without_as",
                    "select (count(*))::int num_events from active_events",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="num_events",
                                expr=ast.TypeCast(
                                    expr=ast.Call(name="count", args=[ast.Field(chain=["*"])]),
                                    type_name="int",
                                ),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["active_events"])),
                    ),
                ),
                (
                    "qualified_field_cast",
                    "select e.event::text as event_name from events e",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="event_name",
                                expr=ast.TypeCast(expr=ast.Field(chain=["e", "event"]), type_name="text"),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
                    ),
                ),
                (
                    "compound_type_cast",
                    "select now()::timestamp with time zone as ts from events",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="ts",
                                expr=ast.TypeCast(
                                    expr=ast.Call(name="now", args=[]),
                                    type_name="timestamp with time zone",
                                ),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    ),
                ),
                (
                    "interval_cast",
                    "select 1::interval as i from events",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="i",
                                expr=ast.TypeCast(expr=ast.Constant(value=1), type_name="interval"),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    ),
                ),
                (
                    "int_cast_with_as",
                    "select 1::int as value",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="value",
                                expr=ast.TypeCast(expr=ast.Constant(value=1), type_name="int"),
                            )
                        ],
                    ),
                ),
                (
                    "literal_cast",
                    "select '123'::int as x from events",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="x",
                                expr=ast.TypeCast(expr=ast.Constant(value="123"), type_name="int"),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    ),
                ),
            ]
        )
        def test_type_cast_alias_parsing(self, _, query, expected):
            self.assertEqual(self._select(query), expected)

        @parameterized.expand(
            [
                ("with_alone", "select 1::with"),
                ("zone_alone", "select 1::zone"),
                ("local_alone", "select 1::local"),
            ]
        )
        def test_type_cast_rejects_partial_with_time_zone_keywords(self, _, query):
            with self.assertRaises(SyntaxError):
                self._select(query)

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
                self._select("select 1 from events LIMIT 1 %"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=1),
                    limit_percent=True,
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT (60 + 7) %"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Add,
                        left=ast.Constant(value=60),
                        right=ast.Constant(value=7),
                    ),
                    limit_percent=True,
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT (select avg(team_id) from events) %"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.SelectQuery(
                        select=[ast.Call(name="avg", args=[ast.Field(chain=["team_id"])])],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    ),
                    limit_percent=True,
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
                self._select("select 1 from events LIMIT 1 % OFFSET 3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=1),
                    limit_percent=True,
                    offset=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 42% OFFSET 20"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=42),
                    limit_percent=True,
                    offset=ast.Constant(value=20),
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

        def test_select_intersect_all(self):
            self.assertEqual(
                self._select("select 1 intersect all select 2"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(select=[ast.Constant(value=1)]),
                    subsequent_select_queries=[
                        SelectSetNode(
                            set_operator="INTERSECT ALL",
                            select_query=ast.SelectQuery(select=[ast.Constant(value=2)]),
                        )
                    ],
                ),
            )

        def test_select_except_all(self):
            self.assertEqual(
                self._select("select 1 except all select 2"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(select=[ast.Constant(value=1)]),
                    subsequent_select_queries=[
                        SelectSetNode(
                            set_operator="EXCEPT ALL",
                            select_query=ast.SelectQuery(select=[ast.Constant(value=2)]),
                        )
                    ],
                ),
            )

        def test_select_set_order_by(self):
            self.assertEqual(
                self._select("select 1 union all select 2 order by 1"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(select=[ast.Constant(value=1)]),
                    subsequent_select_queries=[
                        SelectSetNode(
                            set_operator="UNION ALL",
                            select_query=ast.SelectQuery(
                                select=[ast.Constant(value=2)],
                                order_by=[ast.OrderExpr(expr=ast.Constant(value=1), order="ASC")],
                            ),
                        )
                    ],
                ),
            )

        @parameterized.expand(
            [
                ("union by name", "UNION DISTINCT BY NAME"),
                ("union all by name", "UNION ALL BY NAME"),
                ("union distinct by name", "UNION DISTINCT BY NAME"),
            ]
        )
        def test_select_union_by_name(self, sql_operator, expected_operator):
            self.assertEqual(
                self._select(f"select 1 as a, 2 as b {sql_operator} select 3 as b, 4 as a"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(
                        select=[
                            ast.Alias(alias="a", expr=ast.Constant(value=1)),
                            ast.Alias(alias="b", expr=ast.Constant(value=2)),
                        ]
                    ),
                    subsequent_select_queries=[
                        SelectSetNode(
                            set_operator=expected_operator,
                            select_query=ast.SelectQuery(
                                select=[
                                    ast.Alias(alias="b", expr=ast.Constant(value=3)),
                                    ast.Alias(alias="a", expr=ast.Constant(value=4)),
                                ]
                            ),
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

        def test_ctes_preserve_declaration_order(self):
            node = cast(
                ast.SelectQuery,
                self._select(
                    "with zz_first as (select 1 from events), "
                    "mm_middle as (select * from zz_first), "
                    "aa_last as (select * from mm_middle) "
                    "select * from aa_last"
                ),
            )
            assert isinstance(node.ctes, dict)
            self.assertEqual(list(node.ctes.keys()), ["zz_first", "mm_middle", "aa_last"])

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

        def test_unquoted_reserved_keyword_alias_is_invalid(self):
            with self.assertRaises(SyntaxError):
                self._select("select 1 from")

        def test_quoted_reserved_keyword_identifier(self):
            self.assertEqual(
                self._select('select "from" from events'),
                ast.SelectQuery(
                    select=[ast.Field(chain=["from"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        @parameterized.expand([["id"], ["name"], ["timestamp"], ["time"], ["date"], ["key"]])
        def test_non_reserved_keywords_can_be_used_as_identifiers(self, identifier: str):
            self.assertEqual(
                self._select(f"select {identifier} from events"),
                ast.SelectQuery(
                    select=[ast.Field(chain=[identifier])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

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
                "select <strong><a href='https://google.com'>Hello <em>{event}</em></a>{'a'}</strong> from events"
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

        def test_trailing_semicolon_select(self):
            self.assertEqual(self._select("SELECT 1;"), self._select("SELECT 1"))

            self.assertEqual(self._select("SELECT 1 FROM events;"), self._select("SELECT 1 FROM events"))

            self.assertEqual(
                self._select("SELECT * FROM events WHERE timestamp > now();"),
                self._select("SELECT * FROM events WHERE timestamp > now()"),
            )

            self.assertEqual(
                self._select("SELECT e.event FROM events e JOIN persons p ON e.person_id = p.id;"),
                self._select("SELECT e.event FROM events e JOIN persons p ON e.person_id = p.id"),
            )

            self.assertEqual(self._select("SELECT 1 UNION ALL SELECT 2;"), self._select("SELECT 1 UNION ALL SELECT 2"))

        def test_postgres_style_cast(self):
            self.assertEqual(
                self._expr("x::int"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="int"),
            )
            self.assertEqual(self._expr("'123'::int"), ast.TypeCast(expr=ast.Constant(value="123"), type_name="int"))
            self.assertEqual(self._expr("x::integer"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="integer"))
            self.assertEqual(self._expr("x::text"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="text"))
            self.assertEqual(self._expr("x::float"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="float"))
            self.assertEqual(self._expr("x::boolean"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="boolean"))
            self.assertEqual(self._expr("x::INT"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="int"))
            self.assertEqual(self._expr("x::Text"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="text"))
            self.assertEqual(
                self._expr("a.b::int"),
                ast.TypeCast(expr=ast.Field(chain=["a", "b"]), type_name="int"),
            )
            self.assertEqual(
                self._expr("x::int + 1"),
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Add,
                    left=ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="int"),
                    right=ast.Constant(value=1),
                ),
            )

        def test_cast_with_nested_and_parametric_types(self):
            self.assertEqual(
                self._expr("CAST(x AS STRUCT(a INTEGER, b VARCHAR))"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="struct(a integer, b varchar)"),
            )
            self.assertEqual(
                self._expr("CAST(x AS DECIMAL(10, 2))"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="decimal(10, 2)"),
            )
            self.assertEqual(
                self._expr("CAST(x AS INTEGER[])"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="integer[]"),
            )
            self.assertEqual(
                self._expr("CAST(x AS VARCHAR[3])"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="varchar[3]"),
            )
            self.assertEqual(
                self._expr("CAST(x AS ARRAY(INTEGER))"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="array(integer)"),
            )
            self.assertEqual(
                self._expr("CAST(x AS TUPLE(INTEGER, VARCHAR))"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="tuple(integer, varchar)"),
            )

        def test_with_clause_column_name_list(self):
            node = self._select("WITH cte (a, b) AS (SELECT 1, 2) SELECT * FROM cte")
            assert isinstance(node, ast.SelectQuery)
            assert node.ctes is not None and node.ctes.get("cte") is not None
            cte = node.ctes["cte"]
            assert cte.name == "cte"
            assert cte.columns == ["a", "b"]

        def test_with_recursive(self):
            parsed = self._select("WITH RECURSIVE events AS (SELECT * FROM posthog_event) SELECT * FROM events;")

            expected = SelectQuery(
                ctes={
                    "events": ast.CTE(
                        name="events",
                        expr=SelectQuery(
                            select=[Field(chain=["*"], from_asterisk=False)],
                            select_from=JoinExpr(
                                table=Field(chain=["posthog_event"], from_asterisk=False),
                            ),
                        ),
                        cte_type="subquery",
                        recursive=True,
                    )
                },
                select=[Field(chain=["*"], from_asterisk=False)],
                select_from=JoinExpr(table=Field(chain=["events"])),
            )

            self.assertEqual(parsed, expected)

        def test_cte_materialization_hint_is_none_when_omitted(self):
            parsed = self._select("WITH x AS (SELECT 1) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.materialized is None

        def test_cte_materialization_hint_materialized(self):
            parsed = self._select("WITH x AS MATERIALIZED (SELECT 1) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.materialized is True

        def test_cte_materialization_hint_not_materialized(self):
            parsed = self._select("WITH x AS NOT MATERIALIZED (SELECT 1) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.materialized is False

        def test_with_clause_before_parens_select_set(self):
            self.assertEqual(
                self._select("WITH cte AS (SELECT 1 AS a) (SELECT a FROM cte UNION ALL SELECT a FROM cte)"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(
                        select=[ast.Field(chain=["a"])],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["cte"])),
                        ctes={
                            "cte": ast.CTE(
                                name="cte",
                                expr=ast.SelectQuery(
                                    select=[ast.Alias(alias="a", expr=ast.Constant(value=1))],
                                ),
                                cte_type="subquery",
                            )
                        },
                    ),
                    subsequent_select_queries=[
                        ast.SelectSetNode(
                            set_operator="UNION ALL",
                            select_query=ast.SelectQuery(
                                select=[ast.Field(chain=["a"])],
                                select_from=ast.JoinExpr(table=ast.Field(chain=["cte"])),
                            ),
                        )
                    ],
                ),
            )

        def test_cte_using_key_is_none_when_omitted(self):
            parsed = self._select("WITH RECURSIVE x(a, b) AS (SELECT 1, 2) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.using_key is None

        def test_cte_using_key_single_column(self):
            parsed = self._select("WITH RECURSIVE x(a, b) USING KEY (a) AS (SELECT 1, 2) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.using_key == ["a"]
            assert cte.columns == ["a", "b"]

        def test_cte_using_key_multiple_columns(self):
            parsed = self._select("WITH RECURSIVE x(a, b, c) USING KEY (a, b) AS (SELECT 1, 2, 3) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.using_key == ["a", "b"]
            assert cte.columns == ["a", "b", "c"]

        def test_cte_using_key_without_column_name_list(self):
            parsed = self._select("WITH RECURSIVE x USING KEY (a) AS (SELECT 1) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.using_key == ["a"]
            assert cte.columns is None

        def test_select_from_values(self):
            self.assertEqual(
                self._select("SELECT * FROM (VALUES (1, 'a'), (2, 'b')) AS v(id, name)"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.ValuesQuery(
                            rows=[
                                [ast.Constant(value=1), ast.Constant(value="a")],
                                [ast.Constant(value=2), ast.Constant(value="b")],
                            ]
                        ),
                        alias="v",
                        column_aliases=["id", "name"],
                    ),
                ),
            )

        def test_select_from_values_no_column_aliases(self):
            self.assertEqual(
                self._select("SELECT * FROM (VALUES (1), (2)) AS v"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.ValuesQuery(
                            rows=[
                                [ast.Constant(value=1)],
                                [ast.Constant(value=2)],
                            ]
                        ),
                        alias="v",
                    ),
                ),
            )

        def test_select_from_unpivot(self):
            self.assertEqual(
                self._select(
                    "SELECT field_name, field_value FROM events UNPIVOT (field_value FOR field_name IN (event))"
                ),
                ast.SelectQuery(
                    select=[ast.Field(chain=["field_name"]), ast.Field(chain=["field_value"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.Field(chain=["events"]),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Field(chain=["field_value"]),
                                    name_columns=ast.Field(chain=["field_name"]),
                                    unpivot_values=[ast.Field(chain=["event"])],
                                )
                            ],
                        )
                    ),
                ),
            )

        def test_select_from_unpivot_tuple(self):
            self.assertEqual(
                self._select(
                    "SELECT * FROM events UNPIVOT ((value_a, value_b) FOR (name_a, name_b) IN ((event, uuid)))"
                ),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.Field(chain=["events"]),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Tuple(
                                        exprs=[ast.Field(chain=["value_a"]), ast.Field(chain=["value_b"])]
                                    ),
                                    name_columns=ast.Tuple(
                                        exprs=[ast.Field(chain=["name_a"]), ast.Field(chain=["name_b"])]
                                    ),
                                    unpivot_values=[
                                        ast.Tuple(exprs=[ast.Field(chain=["event"]), ast.Field(chain=["uuid"])])
                                    ],
                                )
                            ],
                        )
                    ),
                ),
            )

        def test_select_from_unpivot_multiple_in(self):
            self.assertEqual(
                self._select("SELECT * FROM events UNPIVOT (field_value FOR field_name IN (event, uuid))"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.Field(chain=["events"]),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Field(chain=["field_value"]),
                                    name_columns=ast.Field(chain=["field_name"]),
                                    unpivot_values=[ast.Field(chain=["event"]), ast.Field(chain=["uuid"])],
                                )
                            ],
                        )
                    ),
                ),
            )

        def test_select_from_unpivot_with_table_alias(self):
            self.assertEqual(
                self._select("SELECT * FROM events e UNPIVOT (field_value FOR field_name IN (event))"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Field(chain=["field_value"]),
                                    name_columns=ast.Field(chain=["field_name"]),
                                    unpivot_values=[ast.Field(chain=["event"])],
                                )
                            ],
                        )
                    ),
                ),
            )

        def test_select_from_pivot(self):
            self.assertEqual(
                self._select("SELECT * FROM events PIVOT (count() FOR event IN ('a', 'b'))"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.PivotExpr(
                            table=ast.Field(chain=["events"]),
                            aggregates=[ast.Call(name="count", args=[])],
                            columns=[
                                ast.PivotColumn(
                                    column=ast.Field(chain=["event"]),
                                    values=[ast.Constant(value="a"), ast.Constant(value="b")],
                                )
                            ],
                            group_by=None,
                        )
                    ),
                ),
            )

        def test_select_from_pivot_multiple_columns(self):
            self.assertEqual(
                self._select(
                    "SELECT * FROM events PIVOT (count() FOR event IN ('a') person_id IN (1, 2) GROUP BY distinct_id)"
                ),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.PivotExpr(
                            table=ast.Field(chain=["events"]),
                            aggregates=[ast.Call(name="count", args=[])],
                            columns=[
                                ast.PivotColumn(
                                    column=ast.Field(chain=["event"]),
                                    values=[ast.Constant(value="a")],
                                ),
                                ast.PivotColumn(
                                    column=ast.Field(chain=["person_id"]),
                                    values=[ast.Constant(value=1), ast.Constant(value=2)],
                                ),
                            ],
                            group_by=[ast.Field(chain=["distinct_id"])],
                        )
                    ),
                ),
            )

        def test_select_from_join_pivot(self):
            self.assertEqual(
                self._select("SELECT 1 FROM events JOIN events AS e2 ON 1 PIVOT (count() FOR events.event IN ('a'))"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.PivotExpr(
                            table=ast.JoinExpr(
                                table=ast.Field(chain=["events"]),
                                next_join=ast.JoinExpr(
                                    join_type="JOIN",
                                    table=ast.Field(chain=["events"]),
                                    alias="e2",
                                    constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                                ),
                            ),
                            aggregates=[ast.Call(name="count", args=[])],
                            columns=[
                                ast.PivotColumn(
                                    column=ast.Field(chain=["events", "event"]),
                                    values=[ast.Constant(value="a")],
                                )
                            ],
                            group_by=None,
                        )
                    ),
                ),
            )

        def test_select_from_unpivot_include_nulls(self):
            self.assertEqual(
                self._select(
                    "SELECT field_name, field_value FROM events UNPIVOT INCLUDE NULLS (field_value FOR field_name IN (event))"
                ),
                ast.SelectQuery(
                    select=[ast.Field(chain=["field_name"]), ast.Field(chain=["field_value"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.Field(chain=["events"]),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Field(chain=["field_value"]),
                                    name_columns=ast.Field(chain=["field_name"]),
                                    unpivot_values=[ast.Field(chain=["event"])],
                                )
                            ],
                            include_nulls=True,
                        )
                    ),
                ),
            )

        def test_select_from_join_unpivot(self):
            self.assertEqual(
                self._select(
                    "SELECT field_name, field_value FROM events JOIN events AS e2 ON 1 "
                    "UNPIVOT (field_value FOR field_name IN (events.event))"
                ),
                ast.SelectQuery(
                    select=[ast.Field(chain=["field_name"]), ast.Field(chain=["field_value"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.JoinExpr(
                                table=ast.Field(chain=["events"]),
                                next_join=ast.JoinExpr(
                                    join_type="JOIN",
                                    table=ast.Field(chain=["events"]),
                                    alias="e2",
                                    constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                                ),
                            ),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Field(chain=["field_value"]),
                                    name_columns=ast.Field(chain=["field_name"]),
                                    unpivot_values=[ast.Field(chain=["events", "event"])],
                                )
                            ],
                        )
                    ),
                ),
            )

        def test_select_positional_join(self):
            self.assertEqual(
                self._select("SELECT * FROM events POSITIONAL JOIN persons"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(table=ast.Field(chain=["persons"]), join_type="POSITIONAL JOIN"),
                    ),
                ),
            )

        def test_select_positional_refs(self):
            self.assertEqual(
                self._select("SELECT #1, #2 FROM events"),
                ast.SelectQuery(
                    select=[ast.PositionalRef(index=1), ast.PositionalRef(index=2)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

    return TestParser
