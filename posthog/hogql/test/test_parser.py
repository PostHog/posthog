from typing import cast, Optional, Dict

import math

from posthog.hogql import ast
from posthog.hogql.errors import HogQLException
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_select
from posthog.hogql.visitor import clear_locations
from posthog.test.base import BaseTest


class TestParser(BaseTest):
    maxDiff = None

    def _expr(self, expr: str, placeholders: Optional[Dict[str, ast.Expr]] = None) -> ast.Expr:
        return clear_locations(parse_expr(expr, placeholders=placeholders))

    def _select(self, query: str, placeholders: Optional[Dict[str, ast.Expr]] = None) -> ast.Expr:
        return clear_locations(parse_select(query, placeholders=placeholders))

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

    def test_conditional(self):
        self.assertEqual(
            self._expr("1 > 2 ? 1 : 2"),
            ast.Call(
                name="if",
                args=[
                    # mypy wants all the named arguments, but we don't really need them
                    ast.CompareOperation(  # type: ignore
                        op=ast.CompareOperationOp.Gt, left=ast.Constant(value=1), right=ast.Constant(value=2)
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
            self._expr("[1, avg()]"), ast.Array(exprs=[ast.Constant(value=1), ast.Call(name="avg", args=[])])
        )
        self.assertEqual(
            self._expr("properties['value']"),
            ast.ArrayAccess(array=ast.Field(chain=["properties"]), property=ast.Constant(value="value")),
        )
        self.assertEqual(
            self._expr("properties[(select 'value')]"),
            ast.ArrayAccess(
                array=ast.Field(chain=["properties"]), property=ast.SelectQuery(select=[ast.Constant(value="value")])
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
            self._expr("(1, avg())"), ast.Tuple(exprs=[ast.Constant(value=1), ast.Call(name="avg", args=[])])
        )
        # needs at least two values to be a tuple
        self.assertEqual(self._expr("(1)"), ast.Constant(value=1))

    def test_lambdas(self):
        self.assertEqual(
            self._expr("arrayMap(x -> x * 2)"),
            ast.Call(
                name="arrayMap",
                args=[
                    ast.Lambda(
                        args=["x"],
                        expr=ast.ArithmeticOperation(
                            op=ast.ArithmeticOperationOp.Mult, left=ast.Field(chain=["x"]), right=ast.Constant(value=2)
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
                            op=ast.ArithmeticOperationOp.Mult, left=ast.Field(chain=["x"]), right=ast.Constant(value=2)
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
                            op=ast.ArithmeticOperationOp.Mult, left=ast.Field(chain=["x"]), right=ast.Field(chain=["y"])
                        ),
                    )
                ],
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
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.ArithmeticOperationOp.Add
            ),
        )
        self.assertEqual(
            self._expr("1 + -2"),
            ast.ArithmeticOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=-2), op=ast.ArithmeticOperationOp.Add
            ),
        )
        self.assertEqual(
            self._expr("1 - 2"),
            ast.ArithmeticOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.ArithmeticOperationOp.Sub
            ),
        )
        self.assertEqual(
            self._expr("1 * 2"),
            ast.ArithmeticOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.ArithmeticOperationOp.Mult
            ),
        )
        self.assertEqual(
            self._expr("1 / 2"),
            ast.ArithmeticOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.ArithmeticOperationOp.Div
            ),
        )
        self.assertEqual(
            self._expr("1 % 2"),
            ast.ArithmeticOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.ArithmeticOperationOp.Mod
            ),
        )
        self.assertEqual(
            self._expr("1 + 2 + 2"),
            ast.ArithmeticOperation(
                left=ast.ArithmeticOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.ArithmeticOperationOp.Add
                ),
                right=ast.Constant(value=2),
                op=ast.ArithmeticOperationOp.Add,
            ),
        )
        self.assertEqual(
            self._expr("1 * 1 * 2"),
            ast.ArithmeticOperation(
                left=ast.ArithmeticOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=1), op=ast.ArithmeticOperationOp.Mult
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
                    left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.ArithmeticOperationOp.Mult
                ),
                op=ast.ArithmeticOperationOp.Add,
            ),
        )
        self.assertEqual(
            self._expr("1 * 1 + 2"),
            ast.ArithmeticOperation(
                left=ast.ArithmeticOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=1), op=ast.ArithmeticOperationOp.Mult
                ),
                right=ast.Constant(value=2),
                op=ast.ArithmeticOperationOp.Add,
            ),
        )

    def test_math_comparison_operations(self):
        self.assertEqual(
            self._expr("1 = 2"),
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationOp.Eq
            ),
        )
        self.assertEqual(
            self._expr("1 == 2"),
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationOp.Eq
            ),
        )
        self.assertEqual(
            self._expr("1 != 2"),
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationOp.NotEq
            ),
        )
        self.assertEqual(
            self._expr("1 < 2"),
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationOp.Lt
            ),
        )
        self.assertEqual(
            self._expr("1 <= 2"),
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationOp.LtEq
            ),
        )
        self.assertEqual(
            self._expr("1 > 2"),
            ast.CompareOperation(left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationOp.Gt),
        )
        self.assertEqual(
            self._expr("1 >= 2"),
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value=2), op=ast.CompareOperationOp.GtEq
            ),
        )

    def test_null_comparison_operations(self):
        self.assertEqual(
            self._expr("1 is null"),
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value=None), op=ast.CompareOperationOp.Eq
            ),
        )
        self.assertEqual(
            self._expr("1 is not null"),
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value=None), op=ast.CompareOperationOp.NotEq
            ),
        )

    def test_like_comparison_operations(self):
        self.assertEqual(
            self._expr("1 like 'a%sd'"),
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationOp.Like
            ),
        )
        self.assertEqual(
            self._expr("1 not like 'a%sd'"),
            # mypy wants all the named arguments, but we don't really need them
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore #type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationOp.NotLike
            ),
        )
        self.assertEqual(
            self._expr("1 ilike 'a%sd'"),
            # mypy wants all the named arguments, but we don't really need them
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore #type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationOp.ILike
            ),
        )
        self.assertEqual(
            self._expr("1 not ilike 'a%sd'"),
            # mypy wants all the named arguments, but we don't really need them
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore #type: ignore
                left=ast.Constant(value=1), right=ast.Constant(value="a%sd"), op=ast.CompareOperationOp.NotILike
            ),
        )

    def test_and_or(self):
        self.assertEqual(
            self._expr("true or false"),
            # mypy wants all the named arguments, but we don't really need them
            ast.Or(exprs=[ast.Constant(value=True), ast.Constant(value=False)]),  # type: ignore
        )
        self.assertEqual(
            self._expr("true and false"),
            # mypy wants all the named arguments, but we don't really need them
            ast.And(exprs=[ast.Constant(value=True), ast.Constant(value=False)]),  # type: ignore
        )
        self.assertEqual(
            self._expr("true and not false"),
            # mypy wants all the named arguments, but we don't really need them
            ast.And(  # type: ignore
                exprs=[ast.Constant(value=True), ast.Not(expr=ast.Constant(value=False))],  # type: ignore
            ),
        )
        self.assertEqual(
            self._expr("true or false or not true or 2"),
            # mypy wants all the named arguments, but we don't really need them
            ast.Or(  # type: ignore
                exprs=[
                    ast.Constant(value=True),
                    ast.Constant(value=False),
                    # mypy wants all the named arguments, but we don't really need them
                    ast.Not(expr=ast.Constant(value=True)),  # type: ignore
                    ast.Constant(value=2),
                ],
            ),
        )
        self.assertEqual(
            self._expr("true or false and not true or 2"),
            ast.Or(
                exprs=[
                    ast.Constant(value=True),
                    # mypy wants all the named arguments, but we don't really need them
                    ast.And(  # type: ignore
                        exprs=[
                            ast.Constant(value=False),
                            ast.Not(expr=ast.Constant(value=True)),  # type: ignore
                        ],
                    ),
                    ast.Constant(value=2),
                ],
            ),
        )

    def test_unary_operations(self):
        self.assertEqual(
            self._expr("not true"),
            # mypy wants all the named arguments, but we don't really need them
            ast.Not(expr=ast.Constant(value=True)),  # type: ignore
        )

    def test_parens(self):
        self.assertEqual(
            self._expr("(1)"),
            ast.Constant(value=1),
        )
        self.assertEqual(
            self._expr("(1 + 1)"),
            ast.ArithmeticOperation(
                left=ast.Constant(value=1), right=ast.Constant(value=1), op=ast.ArithmeticOperationOp.Add
            ),
        )
        self.assertEqual(
            self._expr("1 + (1 + 1)"),
            ast.ArithmeticOperation(
                left=ast.Constant(value=1),
                right=ast.ArithmeticOperation(
                    left=ast.Constant(value=1), right=ast.Constant(value=1), op=ast.ArithmeticOperationOp.Add
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
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore #type: ignore
                left=ast.Field(chain=["event"]), right=ast.Constant(value="$%"), op=ast.CompareOperationOp.Like
            ),
        )

    def test_property_access(self):
        self.assertEqual(
            self._expr("properties.something == 1"),
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore #type: ignore
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
            ast.Call(name="avg", args=[ast.Constant(value=1), ast.Constant(value=2), ast.Constant(value=3)]),
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
            ast.Placeholder(field="foo"),
        )
        self.assertEqual(
            self._expr("{foo}", {"foo": ast.Constant(value="bar")}),
            ast.Constant(value="bar"),
        )
        self.assertEqual(
            self._expr("timestamp < {timestamp}", {"timestamp": ast.Constant(value=123)}),
            # mypy wants all the named arguments, but we don't really need them
            ast.CompareOperation(  # type: ignore #type: ignore
                op=ast.CompareOperationOp.Lt,
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
            self._expr("now() - interval 1 week"),
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
        self.assertEqual(self._select("select 1"), ast.SelectQuery(select=[ast.Constant(value=1)]))
        self.assertEqual(
            self._select("select 1, 4, 'string'"),
            ast.SelectQuery(select=[ast.Constant(value=1), ast.Constant(value=4), ast.Constant(value="string")]),
        )

    def test_select_columns_distinct(self):
        self.assertEqual(
            self._select("select distinct 1"), ast.SelectQuery(select=[ast.Constant(value=1)], distinct=True)
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
                # mypy wants all the named arguments, but we don't really need them
                where=ast.CompareOperation(  # type: ignore #type: ignore
                    op=ast.CompareOperationOp.Eq, left=ast.Constant(value=1), right=ast.Constant(value=2)
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
                # mypy wants all the named arguments, but we don't really need them
                prewhere=ast.CompareOperation(  # type: ignore #type: ignore
                    op=ast.CompareOperationOp.Eq, left=ast.Constant(value=1), right=ast.Constant(value=2)
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
                # mypy wants all the named arguments, but we don't really need them
                having=ast.CompareOperation(  # type: ignore #type: ignore
                    op=ast.CompareOperationOp.Eq, left=ast.Constant(value=1), right=ast.Constant(value=2)
                ),
            ),
        )

    def test_select_complex_wheres(self):
        self.assertEqual(
            self._select("select 1 prewhere 2 != 3 where 1 == 2 having 'string' like '%a%'"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                where=ast.CompareOperation(  # type: ignore #type: ignore
                    op=ast.CompareOperationOp.Eq, left=ast.Constant(value=1), right=ast.Constant(value=2)
                ),
                # mypy wants all the named arguments, but we don't really need them
                prewhere=ast.CompareOperation(  # type: ignore #type: ignore
                    op=ast.CompareOperationOp.NotEq, left=ast.Constant(value=2), right=ast.Constant(value=3)
                ),
                # mypy wants all the named arguments, but we don't really need them
                having=ast.CompareOperation(  # type: ignore #type: ignore
                    op=ast.CompareOperationOp.Like, left=ast.Constant(value="string"), right=ast.Constant(value="%a%")
                ),
            ),
        )

    def test_select_from(self):
        self.assertEqual(
            self._select("select 1 from events"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
            ),
        )
        self.assertEqual(
            self._select("select 1 from events as e"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),  # type: ignore
            ),
        )
        self.assertEqual(
            self._select("select 1 from events e"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),  # type: ignore
            ),
        )
        self.assertEqual(
            self._select("select 1 from complex.table"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["complex", "table"])),  # type: ignore
            ),
        )
        self.assertEqual(
            self._select("select 1 from complex.table as a"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["complex", "table"]), alias="a"),  # type: ignore
            ),
        )
        self.assertEqual(
            self._select("select 1 from complex.table a"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["complex", "table"]), alias="a"),  # type: ignore
            ),
        )
        self.assertEqual(
            self._select("select 1 from (select 1 from events)"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(
                    table=ast.SelectQuery(
                        # mypy wants all the named arguments, but we don't really need them
                        select=[ast.Constant(value=1)],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
                    )
                ),
            ),
        )
        self.assertEqual(
            self._select("select 1 from (select 1 from events) as sq"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(
                    # mypy wants all the named arguments, but we don't really need them
                    table=ast.SelectQuery(  # type: ignore
                        select=[ast.Constant(value=1)],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
                    ),
                    alias="sq",
                ),
            ),
        )

    def test_select_from_join(self):
        self.assertEqual(
            self._select("select 1 from events JOIN events2 ON 1"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(  # type: ignore
                    table=ast.Field(chain=["events"]),
                    # mypy wants all the named arguments, but we don't really need them
                    next_join=ast.JoinExpr(  # type: ignore
                        join_type="JOIN",
                        table=ast.Field(chain=["events2"]),
                        constraint=ast.JoinConstraint(expr=ast.Constant(value=1)),
                    ),
                ),
            ),
        )
        self.assertEqual(
            self._select("select * from events LEFT OUTER JOIN events2 ON 1"),
            ast.SelectQuery(
                select=[ast.Field(chain=["*"])],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(  # type: ignore
                    table=ast.Field(chain=["events"]),
                    # mypy wants all the named arguments, but we don't really need them
                    next_join=ast.JoinExpr(  # type: ignore
                        join_type="LEFT OUTER JOIN",
                        table=ast.Field(chain=["events2"]),
                        constraint=ast.JoinConstraint(expr=ast.Constant(value=1)),
                    ),
                ),
            ),
        )
        self.assertEqual(
            self._select("select 1 from events LEFT OUTER JOIN events2 ON 1 ANY RIGHT JOIN events3 ON 2"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(  # type: ignore
                    table=ast.Field(chain=["events"]),
                    # mypy wants all the named arguments, but we don't really need them
                    next_join=ast.JoinExpr(  # type: ignore
                        join_type="LEFT OUTER JOIN",
                        table=ast.Field(chain=["events2"]),
                        constraint=ast.JoinConstraint(expr=ast.Constant(value=1)),
                        # mypy wants all the named arguments, but we don't really need them
                        next_join=ast.JoinExpr(  # type: ignore
                            join_type="RIGHT ANY JOIN",
                            table=ast.Field(chain=["events3"]),
                            constraint=ast.JoinConstraint(expr=ast.Constant(value=2)),
                        ),
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
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(  # type: ignore
                    table=ast.Field(chain=["events"]),
                    alias="e",
                    # mypy wants all the named arguments, but we don't really need them
                    next_join=ast.JoinExpr(  # type: ignore
                        join_type="LEFT JOIN",
                        table=ast.Field(chain=["person_distinct_id"]),
                        alias="pdi",
                        # mypy wants all the named arguments, but we don't really need them
                        constraint=ast.JoinConstraint(
                            expr=ast.CompareOperation(  # type: ignore #type: ignore
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["pdi", "distinct_id"]),
                                right=ast.Field(chain=["e", "distinct_id"]),
                            )
                        ),
                        # mypy wants all the named arguments, but we don't really need them
                        next_join=ast.JoinExpr(  # type: ignore
                            join_type="LEFT JOIN",
                            table=ast.Field(chain=["persons"]),
                            alias="p",
                            # mypy wants all the named arguments, but we don't really need them
                            constraint=ast.JoinConstraint(
                                expr=ast.CompareOperation(  # type: ignore #type: ignore
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["p", "id"]),
                                    right=ast.Field(chain=["pdi", "person_id"]),
                                )
                            ),
                        ),
                    ),
                ),
            ),
        )

    def test_select_group_by(self):
        self.assertEqual(
            self._select("select 1 from events GROUP BY 1, event"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
                group_by=[ast.Constant(value=1), ast.Field(chain=["event"])],
            ),
        )

    def test_order_by(self):
        self.assertEqual(
            parse_order_expr("1 ASC"),
            ast.OrderExpr(expr=ast.Constant(value=1, start=0, end=1), order="ASC", start=0, end=5),
        )
        self.assertEqual(
            parse_order_expr("event"),
            ast.OrderExpr(expr=ast.Field(chain=["event"], start=0, end=5), order="ASC", start=0, end=5),
        )
        self.assertEqual(
            parse_order_expr("timestamp DESC"),
            ast.OrderExpr(expr=ast.Field(chain=["timestamp"], start=0, end=9), order="DESC", start=0, end=14),
        )

    def test_select_order_by(self):
        self.assertEqual(
            self._select("select 1 from events ORDER BY 1 ASC, event, timestamp DESC"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
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
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
                limit=ast.Constant(value=1),
            ),
        )
        self.assertEqual(
            self._select("select 1 from events LIMIT 1 OFFSET 3"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
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
            self._select("select 1 from events LIMIT 1 OFFSET 3 BY 1, event"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
                limit=ast.Constant(value=1),
                offset=ast.Constant(value=3),
                limit_by=[ast.Constant(value=1), ast.Field(chain=["event"])],
            ),
        )

    def test_select_placeholders(self):
        self.assertEqual(
            self._select("select 1 where 1 == {hogql_val_1}"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                where=ast.CompareOperation(  # type: ignore #type: ignore
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Constant(value=1),
                    right=ast.Placeholder(field="hogql_val_1"),
                ),
            ),
        )
        self.assertEqual(
            self._select("select 1 where 1 == {hogql_val_1}", {"hogql_val_1": ast.Constant(value="bar")}),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                where=ast.CompareOperation(  # type: ignore #type: ignore
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Constant(value=1),
                    right=ast.Constant(value="bar"),
                ),
            ),
        )

    def test_select_union_all(self):
        self.assertEqual(
            self._select("select 1 union all select 2 union all select 3"),
            ast.SelectUnionQuery(
                select_queries=[
                    ast.SelectQuery(select=[ast.Constant(value=1)]),
                    ast.SelectQuery(select=[ast.Constant(value=2)]),
                    ast.SelectQuery(select=[ast.Constant(value=3)]),
                ]
            ),
        )

    def test_sample_clause(self):
        self.assertEqual(
            self._select("select 1 from events sample 1/10 offset 999"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(  # type: ignore
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
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(  # type: ignore
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
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(  # type: ignore
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
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(  # type: ignore
                    table=ast.Field(chain=["events"]),
                    # mypy wants all the named arguments, but we don't really need them
                    sample=ast.SampleExpr(  # type: ignore
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
                ctes={"boo": ast.CTE(name="boo", expr=ast.Field(chain=["event"]), cte_type="column")},
                select=[ast.Field(chain=["boo"])],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
            ),
        )
        self.assertEqual(
            self._select("with count() as kokku select kokku from events"),
            ast.SelectQuery(
                ctes={"kokku": ast.CTE(name="kokku", expr=ast.Call(name="count", args=[]), cte_type="column")},
                select=[ast.Field(chain=["kokku"])],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
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
                            # mypy wants all the named arguments, but we don't really need them
                            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
                        ),
                        cte_type="subquery",
                    )
                },
                select=[ast.Field(chain=["*"])],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["customers"])),  # type: ignore
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
                            # mypy wants all the named arguments, but we don't really need them
                            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
                        ),
                        cte_type="subquery",
                    ),
                    "sad": ast.CTE(name="sad", expr=ast.Constant(value=":("), cte_type="column"),
                },
                select=[ast.Field(chain=["sad"])],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["happy"])),  # type: ignore
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
                            # mypy wants all the named arguments, but we don't really need them
                            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
                        ),
                        cte_type="subquery",
                    ),
                    "final": ast.CTE(
                        name="final",
                        expr=ast.SelectQuery(
                            select=[ast.Field(chain=["tt"])],
                            # mypy wants all the named arguments, but we don't really need them
                            select_from=ast.JoinExpr(table=ast.Field(chain=["users"])),  # type: ignore
                        ),
                        cte_type="subquery",
                    ),
                },
                select=[ast.Field(chain=["*"])],
                # mypy wants all the named arguments, but we don't really need them
                select_from=ast.JoinExpr(table=ast.Field(chain=["final"])),  # type: ignore
            ),
        )

    def test_case_when(self):
        self.assertEqual(
            self._expr("case when 1 then 2 else 3 end"),
            ast.Call(name="if", args=[ast.Constant(value=1), ast.Constant(value=2), ast.Constant(value=3)]),
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
                        args=[ast.Field(chain=["timestamp"])],
                        over_expr=ast.WindowExpr(
                            partition_by=[ast.Field(chain=["person", "id"])],
                            order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
                            frame_method="ROWS",
                            frame_start=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=None),
                            frame_end=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=1),
                        ),
                    ),
                ),
            ],
            # mypy wants all the named arguments, but we don't really need them
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
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
                        args=[ast.Field(chain=["timestamp"])],
                        over_identifier="win1",
                    ),
                ),
            ],
            # mypy wants all the named arguments, but we don't really need them
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),  # type: ignore
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

    def test_parser_error_start_end(self):
        query = "SELECT person.id as true FROM events"
        with self.assertRaises(HogQLException) as e:
            self._select(query)
        self.assertEqual(e.exception.start, 7)
        self.assertEqual(e.exception.end, 24)
