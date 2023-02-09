from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import ResolverException, resolve_symbols
from posthog.test.base import BaseTest


class TestResolver(BaseTest):
    def test_resolve_events_table(self):
        expr = parse_select("SELECT event, events.timestamp FROM events WHERE events.event = 'test'")
        resolve_symbols(expr)

        events_table_symbol = ast.TableSymbol(table_name="events")
        event_field_symbol = ast.FieldSymbol(name="event", table=events_table_symbol)
        timestamp_field_symbol = ast.FieldSymbol(name="timestamp", table=events_table_symbol)
        select_query_symbol = ast.SelectQuerySymbol(
            aliases={},
            columns={"event": event_field_symbol, "timestamp": timestamp_field_symbol},
            tables={"events": events_table_symbol},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Field(chain=["event"], symbol=event_field_symbol),
                ast.Field(chain=["events", "timestamp"], symbol=timestamp_field_symbol),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], symbol=events_table_symbol),
                alias="events",
                symbol=events_table_symbol,
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["events", "event"], symbol=event_field_symbol),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", symbol=ast.ConstantSymbol(value="test")),
            ),
            symbol=select_query_symbol,
        )

        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.symbol, expected.symbol)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_alias(self):
        expr = parse_select("SELECT event, e.timestamp FROM events e WHERE e.event = 'test'")
        resolve_symbols(expr)

        events_table_symbol = ast.TableSymbol(table_name="events")
        event_field_symbol = ast.FieldSymbol(name="event", table=events_table_symbol)
        timestamp_field_symbol = ast.FieldSymbol(name="timestamp", table=events_table_symbol)
        select_query_symbol = ast.SelectQuerySymbol(
            aliases={},
            columns={"event": event_field_symbol, "timestamp": timestamp_field_symbol},
            tables={"e": ast.TableAliasSymbol(name="e", symbol=events_table_symbol)},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Field(chain=["event"], symbol=event_field_symbol),
                ast.Field(chain=["e", "timestamp"], symbol=timestamp_field_symbol),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], symbol=events_table_symbol),
                alias="e",
                symbol=ast.TableAliasSymbol(name="e", symbol=events_table_symbol),
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["e", "event"], symbol=event_field_symbol),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", symbol=ast.ConstantSymbol(value="test")),
            ),
            symbol=select_query_symbol,
        )

        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.symbol, expected.symbol)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_column_alias(self):
        expr = parse_select("SELECT event as ee, ee, ee as e, e.timestamp FROM events e WHERE e.event = 'test'")
        resolve_symbols(expr)

        events_table_symbol = ast.TableSymbol(table_name="events")
        event_field_symbol = ast.FieldSymbol(name="event", table=events_table_symbol)
        timestamp_field_symbol = ast.FieldSymbol(name="timestamp", table=events_table_symbol)

        select_query_symbol = ast.SelectQuerySymbol(
            aliases={
                "ee": ast.ColumnAliasSymbol(name="ee", symbol=event_field_symbol),
                "e": ast.ColumnAliasSymbol(name="e", symbol=event_field_symbol),
            },
            columns={
                "ee": ast.ColumnAliasSymbol(name="ee", symbol=event_field_symbol),
                "e": ast.ColumnAliasSymbol(name="e", symbol=event_field_symbol),
                "timestamp": timestamp_field_symbol,
            },
            tables={"e": ast.TableAliasSymbol(name="e", symbol=events_table_symbol)},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="ee",
                    expr=ast.Field(chain=["event"], symbol=event_field_symbol),
                    symbol=select_query_symbol.aliases["ee"],
                ),
                ast.Field(chain=["ee"], symbol=select_query_symbol.aliases["ee"]),
                ast.Alias(
                    alias="e",
                    expr=ast.Field(chain=["ee"], symbol=select_query_symbol.aliases["ee"]),
                    symbol=select_query_symbol.aliases["e"],
                ),
                ast.Field(chain=["e", "timestamp"], symbol=timestamp_field_symbol),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], symbol=events_table_symbol),
                alias="e",
                symbol=select_query_symbol.tables["e"],
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["e", "event"], symbol=event_field_symbol),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", symbol=ast.ConstantSymbol(value="test")),
            ),
            symbol=select_query_symbol,
        )
        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.symbol, expected.symbol)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_column_alias_inside_subquery(self):
        expr = parse_select("SELECT b FROM (select event as b, timestamp as c from events) e WHERE e.b = 'test'")
        resolve_symbols(expr)
        events_table_symbol = ast.TableSymbol(table_name="events")
        event_field_symbol = ast.FieldSymbol(name="event", table=events_table_symbol)
        timestamp_field_symbol = ast.FieldSymbol(name="timestamp", table=events_table_symbol)
        inner_select_symbol = ast.SelectQuerySymbol(
            aliases={
                "b": ast.ColumnAliasSymbol(name="b", symbol=event_field_symbol),
                "c": ast.ColumnAliasSymbol(name="c", symbol=timestamp_field_symbol),
            },
            columns={
                "b": ast.ColumnAliasSymbol(name="b", symbol=event_field_symbol),
                "c": ast.ColumnAliasSymbol(name="c", symbol=timestamp_field_symbol),
            },
            tables={
                "events": events_table_symbol,
            },
        )
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["b"],
                    symbol=ast.ColumnAliasSymbol(
                        name="b",
                        symbol=event_field_symbol,
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="b",
                            expr=ast.Field(chain=["event"], symbol=event_field_symbol),
                            symbol=ast.ColumnAliasSymbol(
                                name="b",
                                symbol=event_field_symbol,
                            ),
                        ),
                        ast.Alias(
                            alias="c",
                            expr=ast.Field(chain=["timestamp"], symbol=timestamp_field_symbol),
                            symbol=ast.ColumnAliasSymbol(
                                name="c",
                                symbol=timestamp_field_symbol,
                            ),
                        ),
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"], symbol=events_table_symbol),
                        alias="events",
                        symbol=events_table_symbol,
                    ),
                    symbol=inner_select_symbol,
                ),
                alias="e",
                symbol=ast.TableAliasSymbol(name="e", symbol=inner_select_symbol),
            ),
            where=ast.CompareOperation(
                left=ast.Field(
                    chain=["e", "b"],
                    symbol=ast.ColumnAliasSymbol(
                        name="b",
                        symbol=event_field_symbol,
                    ),
                ),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", symbol=ast.ConstantSymbol(value="test")),
            ),
            symbol=ast.SelectQuerySymbol(
                aliases={},
                columns={
                    "b": ast.ColumnAliasSymbol(name="b", symbol=event_field_symbol),
                },
                tables={"e": ast.TableAliasSymbol(name="e", symbol=inner_select_symbol)},
            ),
        )
        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.symbol, expected.symbol)
        self.assertEqual(expr, expected)

    def test_resolve_subquery_no_field_access(self):
        # From ClickHouse's GitHub: "Aliases defined outside of subquery are not visible in subqueries (but see below)."
        expr = parse_select(
            "SELECT event, (select count() from events where event = e.event) as c FROM events e where event = '$pageview'"
        )
        with self.assertRaises(ResolverException) as e:
            resolve_symbols(expr)
        self.assertEqual(str(e.exception), 'Cannot resolve symbol: "e"')

    def test_resolve_errors(self):
        queries = [
            "SELECT event, (select count() from events where event = x.event) as c FROM events x where event = '$pageview'",
            "SELECT x, (SELECT 1 AS x)",
            "SELECT x IN (SELECT 1 AS x)",
            "SELECT events.x FROM (SELECT event as x FROM events) AS t",
            "SELECT x.y FROM (SELECT event as y FROM events AS x) AS t",
        ]
        for query in queries:
            with self.assertRaises(ResolverException) as e:
                resolve_symbols(parse_select(query))
            self.assertIn("Cannot resolve symbol", str(e.exception))


# "with 2 as a select 1 as a" -> "Different expressions with the same alias a:"
# "with 2 as b, 3 as c select (select 1 as b) as a, b, c" -> "Different expressions with the same alias b:"
# "select a, b, e.c from (select 1 as a, 2 as b, 3 as c) as e" -> 1, 2, 3

# # good
# SELECT t.x FROM (SELECT 1 AS x) AS t;
# SELECT t.x FROM (SELECT x FROM tbl) AS t;
# SELECT x FROM (SELECT x FROM tbl) AS t;
# SELECT 1 AS x, x, x + 1;
# SELECT x, x + 1, 1 AS x;
# SELECT x, 1 + (2 + (3 AS x));
# "SELECT x IN (SELECT 1 AS x) FROM (SELECT 1 AS x)",
