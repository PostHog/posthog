from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
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

    def test_select_columns(self):
        self.assertEqual(parse_select("select 1"), ast.SelectQuery(select=[ast.Constant(value=1)]))
        self.assertEqual(
            parse_select("select 1, 4, 'string'"),
            ast.SelectQuery(select=[ast.Constant(value=1), ast.Constant(value=4), ast.Constant(value="string")]),
        )

    def test_select_columns_distinct(self):
        self.assertEqual(
            parse_select("select distinct 1"), ast.SelectQuery(select=[ast.Constant(value=1)], distinct=True)
        )

    def test_select_where(self):
        self.assertEqual(
            parse_select("select 1 where true"),
            ast.SelectQuery(select=[ast.Constant(value=1)], where=ast.Constant(value=True)),
        )
        self.assertEqual(
            parse_select("select 1 where 1 == 2"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                where=ast.CompareOperation(
                    op=ast.CompareOperationType.Eq, left=ast.Constant(value=1), right=ast.Constant(value=2)
                ),
            ),
        )

    def test_select_prewhere(self):
        self.assertEqual(
            parse_select("select 1 prewhere true"),
            ast.SelectQuery(select=[ast.Constant(value=1)], prewhere=ast.Constant(value=True)),
        )
        self.assertEqual(
            parse_select("select 1 prewhere 1 == 2"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                prewhere=ast.CompareOperation(
                    op=ast.CompareOperationType.Eq, left=ast.Constant(value=1), right=ast.Constant(value=2)
                ),
            ),
        )

    def test_select_having(self):
        self.assertEqual(
            parse_select("select 1 having true"),
            ast.SelectQuery(select=[ast.Constant(value=1)], having=ast.Constant(value=True)),
        )
        self.assertEqual(
            parse_select("select 1 having 1 == 2"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                having=ast.CompareOperation(
                    op=ast.CompareOperationType.Eq, left=ast.Constant(value=1), right=ast.Constant(value=2)
                ),
            ),
        )

    def test_select_complex_wheres(self):
        self.assertEqual(
            parse_select("select 1 prewhere 2 != 3 where 1 == 2 having 'string' like '%a%'"),
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

    def test_select_from(self):
        self.assertEqual(
            parse_select("select 1 from events"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)], select_from=ast.JoinExpr(table=ast.Field(chain=["events"]))
            ),
        )
        self.assertEqual(
            parse_select("select 1 from events as e"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
            ),
        )
        self.assertEqual(
            parse_select("select 1 from complex.table"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(table=ast.Field(chain=["complex", "table"])),
            ),
        )
        self.assertEqual(
            parse_select("select 1 from complex.table as a"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(table=ast.Field(chain=["complex", "table"]), alias="a"),
            ),
        )
        self.assertEqual(
            parse_select("select 1 from (select 1 from events)"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(
                    table=ast.SelectQuery(
                        select=[ast.Constant(value=1)], select_from=ast.JoinExpr(table=ast.Field(chain=["events"]))
                    )
                ),
            ),
        )
        self.assertEqual(
            parse_select("select 1 from (select 1 from events) as sq"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(
                    table=ast.SelectQuery(
                        select=[ast.Constant(value=1)], select_from=ast.JoinExpr(table=ast.Field(chain=["events"]))
                    ),
                    alias="sq",
                ),
            ),
        )

    def test_select_from_join(self):
        self.assertEqual(
            parse_select("select 1 from events JOIN events2 ON 1"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=["events"]),
                    join_type="JOIN",
                    join_constraint=ast.Constant(value=1),
                    join_expr=ast.JoinExpr(table=ast.Field(chain=["events2"])),
                ),
            ),
        )
        self.assertEqual(
            parse_select("select * from events LEFT OUTER JOIN events2 ON 1"),
            ast.SelectQuery(
                select=[ast.Field(chain=["*"])],
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=["events"]),
                    join_type="LEFT OUTER JOIN",
                    join_constraint=ast.Constant(value=1),
                    join_expr=ast.JoinExpr(table=ast.Field(chain=["events2"])),
                ),
            ),
        )
        self.assertEqual(
            parse_select("select 1 from events LEFT OUTER JOIN events2 ON 1 ANY RIGHT JOIN events3 ON 2"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=["events"]),
                    join_type="LEFT OUTER JOIN",
                    join_constraint=ast.Constant(value=1),
                    join_expr=ast.JoinExpr(
                        table=ast.Field(chain=["events2"]),
                        join_type="RIGHT ANY JOIN",
                        join_constraint=ast.Constant(value=2),
                        join_expr=ast.JoinExpr(table=ast.Field(chain=["events3"])),
                    ),
                ),
            ),
        )

    def test_select_group_by(self):
        self.assertEqual(
            parse_select("select 1 from events GROUP BY 1, event"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                group_by=[ast.Constant(value=1), ast.Field(chain=["event"])],
            ),
        )

    def test_select_order_by(self):
        self.assertEqual(
            parse_select("select 1 from events ORDER BY 1 ASC, event, timestamp DESC"),
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
            parse_select("select 1 from events LIMIT 1"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                limit=ast.Constant(value=1),
            ),
        )
        self.assertEqual(
            parse_select("select 1 from events LIMIT 1 OFFSET 3"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                limit=ast.Constant(value=1),
                offset=ast.Constant(value=3),
            ),
        )
        self.assertEqual(
            parse_select("select 1 from events LIMIT 1 OFFSET 3 WITH TIES"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                limit=ast.Constant(value=1),
                limit_with_ties=True,
                offset=ast.Constant(value=3),
            ),
        )
        self.assertEqual(
            parse_select("select 1 from events LIMIT 1 OFFSET 3 BY 1, event"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                limit=ast.Constant(value=1),
                offset=ast.Constant(value=3),
                limit_by=[ast.Constant(value=1), ast.Field(chain=["event"])],
            ),
        )

    def test_select_placeholders(self):
        self.assertEqual(
            parse_select("select 1 where 1 == {hogql_val_1}"),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                where=ast.CompareOperation(
                    op=ast.CompareOperationType.Eq,
                    left=ast.Constant(value=1),
                    right=ast.Placeholder(field="hogql_val_1"),
                ),
            ),
        )
        self.assertEqual(
            parse_select("select 1 where 1 == {hogql_val_1}", {"hogql_val_1": ast.Constant(value="bar")}),
            ast.SelectQuery(
                select=[ast.Constant(value=1)],
                where=ast.CompareOperation(
                    op=ast.CompareOperationType.Eq,
                    left=ast.Constant(value=1),
                    right=ast.Constant(value="bar"),
                ),
            ),
        )
