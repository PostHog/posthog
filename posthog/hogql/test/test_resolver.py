from posthog.hogql import ast
from posthog.hogql.database import database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import ResolverException, resolve_symbols
from posthog.test.base import BaseTest


class TestResolver(BaseTest):
    def test_resolve_events_table(self):
        expr = parse_select("SELECT event, events.timestamp FROM events WHERE events.event = 'test'")
        resolve_symbols(expr)

        events_table_symbol = ast.TableSymbol(table=database.events)
        event_field_symbol = ast.FieldSymbol(name="event", table=events_table_symbol)
        timestamp_field_symbol = ast.FieldSymbol(name="timestamp", table=events_table_symbol)
        select_query_symbol = ast.SelectQuerySymbol(
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

        events_table_symbol = ast.TableSymbol(table=database.events)
        events_table_alias_symbol = ast.TableAliasSymbol(name="e", table=events_table_symbol)
        event_field_symbol = ast.FieldSymbol(name="event", table=events_table_alias_symbol)
        timestamp_field_symbol = ast.FieldSymbol(name="timestamp", table=events_table_alias_symbol)
        select_query_symbol = ast.SelectQuerySymbol(
            columns={"event": event_field_symbol, "timestamp": timestamp_field_symbol},
            tables={"e": events_table_alias_symbol},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Field(chain=["event"], symbol=event_field_symbol),
                ast.Field(chain=["e", "timestamp"], symbol=timestamp_field_symbol),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], symbol=events_table_symbol),
                alias="e",
                symbol=events_table_alias_symbol,
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

        events_table_symbol = ast.TableSymbol(table=database.events)
        events_table_alias_symbol = ast.TableAliasSymbol(name="e", table=events_table_symbol)
        event_field_symbol = ast.FieldSymbol(name="event", table=events_table_alias_symbol)
        timestamp_field_symbol = ast.FieldSymbol(name="timestamp", table=events_table_alias_symbol)

        select_query_symbol = ast.SelectQuerySymbol(
            aliases={
                "ee": ast.FieldAliasSymbol(name="ee", symbol=event_field_symbol),
                "e": ast.FieldAliasSymbol(name="e", symbol=ast.FieldAliasSymbol(name="ee", symbol=event_field_symbol)),
            },
            columns={
                "ee": ast.FieldAliasSymbol(name="ee", symbol=event_field_symbol),
                "e": ast.FieldAliasSymbol(name="e", symbol=ast.FieldAliasSymbol(name="ee", symbol=event_field_symbol)),
                "timestamp": timestamp_field_symbol,
            },
            tables={"e": events_table_alias_symbol},
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
                    symbol=select_query_symbol.aliases["e"],  # is ee ?
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
        inner_events_table_symbol = ast.TableSymbol(table=database.events)
        inner_event_field_symbol = ast.FieldAliasSymbol(
            name="b", symbol=ast.FieldSymbol(name="event", table=inner_events_table_symbol)
        )
        timestamp_field_symbol = ast.FieldSymbol(name="timestamp", table=inner_events_table_symbol)
        timstamp_alias_symbol = ast.FieldAliasSymbol(name="c", symbol=timestamp_field_symbol)
        inner_select_symbol = ast.SelectQuerySymbol(
            aliases={
                "b": inner_event_field_symbol,
                "c": ast.FieldAliasSymbol(name="c", symbol=timestamp_field_symbol),
            },
            columns={
                "b": inner_event_field_symbol,
                "c": ast.FieldAliasSymbol(name="c", symbol=timestamp_field_symbol),
            },
            tables={
                "events": inner_events_table_symbol,
            },
        )
        select_alias_symbol = ast.SelectQueryAliasSymbol(name="e", symbol=inner_select_symbol)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["b"],
                    symbol=ast.FieldSymbol(
                        name="b",
                        table=ast.SelectQueryAliasSymbol(name="e", symbol=inner_select_symbol),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="b",
                            expr=ast.Field(chain=["event"], symbol=inner_event_field_symbol.symbol),
                            symbol=inner_event_field_symbol,
                        ),
                        ast.Alias(
                            alias="c",
                            expr=ast.Field(chain=["timestamp"], symbol=timestamp_field_symbol),
                            symbol=timstamp_alias_symbol,
                        ),
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"], symbol=inner_events_table_symbol),
                        symbol=inner_events_table_symbol,
                    ),
                    symbol=inner_select_symbol,
                ),
                alias="e",
                symbol=select_alias_symbol,
            ),
            where=ast.CompareOperation(
                left=ast.Field(
                    chain=["e", "b"],
                    symbol=ast.FieldSymbol(name="b", table=select_alias_symbol),
                ),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", symbol=ast.ConstantSymbol(value="test")),
            ),
            symbol=ast.SelectQuerySymbol(
                aliases={},
                columns={"b": ast.FieldSymbol(name="b", table=select_alias_symbol)},
                tables={"e": select_alias_symbol},
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
        self.assertEqual(str(e.exception), "Unable to resolve field: e")

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
            self.assertIn("Unable to resolve field:", str(e.exception))

    def test_resolve_lazy_pdi_person_table(self):
        expr = parse_select("select distinct_id, person.id from person_distinct_ids")
        resolve_symbols(expr)
        pdi_table_symbol = ast.TableSymbol(table=database.person_distinct_ids)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["distinct_id"],
                    symbol=ast.FieldSymbol(name="distinct_id", table=pdi_table_symbol),
                ),
                ast.Field(
                    chain=["person", "id"],
                    symbol=ast.FieldSymbol(
                        name="id",
                        table=ast.LazyTableSymbol(
                            table=pdi_table_symbol, field="person", joined_table=database.person_distinct_ids.person
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["person_distinct_ids"], symbol=pdi_table_symbol),
                symbol=pdi_table_symbol,
            ),
            symbol=ast.SelectQuerySymbol(
                aliases={},
                anonymous_tables=[],
                columns={
                    "distinct_id": ast.FieldSymbol(name="distinct_id", table=pdi_table_symbol),
                    "id": ast.FieldSymbol(
                        name="id",
                        table=ast.LazyTableSymbol(
                            table=pdi_table_symbol,
                            joined_table=database.person_distinct_ids.person,
                            field="person",
                        ),
                    ),
                },
                tables={"person_distinct_ids": pdi_table_symbol},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.symbol, expected.symbol)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_table(self):
        expr = parse_select("select event, pdi.person_id from events")
        resolve_symbols(expr)
        events_table_symbol = ast.TableSymbol(table=database.events)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    symbol=ast.FieldSymbol(name="event", table=events_table_symbol),
                ),
                ast.Field(
                    chain=["pdi", "person_id"],
                    symbol=ast.FieldSymbol(
                        name="person_id",
                        table=ast.LazyTableSymbol(
                            table=events_table_symbol, field="pdi", joined_table=database.events.pdi
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], symbol=events_table_symbol),
                symbol=events_table_symbol,
            ),
            symbol=ast.SelectQuerySymbol(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldSymbol(name="event", table=events_table_symbol),
                    "person_id": ast.FieldSymbol(
                        name="person_id",
                        table=ast.LazyTableSymbol(
                            table=events_table_symbol,
                            joined_table=database.events.pdi,
                            field="pdi",
                        ),
                    ),
                },
                tables={"events": events_table_symbol},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.symbol, expected.symbol)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_table_aliased(self):
        expr = parse_select("select event, e.pdi.person_id from events e")
        resolve_symbols(expr)
        events_table_symbol = ast.TableSymbol(table=database.events)
        events_table_alias_symbol = ast.TableAliasSymbol(table=events_table_symbol, name="e")
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    symbol=ast.FieldSymbol(name="event", table=events_table_alias_symbol),
                ),
                ast.Field(
                    chain=["e", "pdi", "person_id"],
                    symbol=ast.FieldSymbol(
                        name="person_id",
                        table=ast.LazyTableSymbol(
                            table=events_table_alias_symbol, field="pdi", joined_table=database.events.pdi
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], symbol=events_table_symbol),
                alias="e",
                symbol=events_table_alias_symbol,
            ),
            symbol=ast.SelectQuerySymbol(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldSymbol(name="event", table=events_table_alias_symbol),
                    "person_id": ast.FieldSymbol(
                        name="person_id",
                        table=ast.LazyTableSymbol(
                            table=events_table_alias_symbol,
                            joined_table=database.events.pdi,
                            field="pdi",
                        ),
                    ),
                },
                tables={"e": events_table_alias_symbol},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.symbol, expected.symbol)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_person_table(self):
        expr = parse_select("select event, pdi.person.id from events")
        resolve_symbols(expr)
        events_table_symbol = ast.TableSymbol(table=database.events)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    symbol=ast.FieldSymbol(name="event", table=events_table_symbol),
                ),
                ast.Field(
                    chain=["pdi", "person", "id"],
                    symbol=ast.FieldSymbol(
                        name="id",
                        table=ast.LazyTableSymbol(
                            table=ast.LazyTableSymbol(
                                table=events_table_symbol, field="pdi", joined_table=database.events.pdi
                            ),
                            field="person",
                            joined_table=database.events.pdi.table.person,
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], symbol=events_table_symbol),
                symbol=events_table_symbol,
            ),
            symbol=ast.SelectQuerySymbol(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldSymbol(name="event", table=events_table_symbol),
                    "id": ast.FieldSymbol(
                        name="id",
                        table=ast.LazyTableSymbol(
                            table=ast.LazyTableSymbol(
                                table=events_table_symbol, field="pdi", joined_table=database.events.pdi
                            ),
                            field="person",
                            joined_table=database.events.pdi.table.person,
                        ),
                    ),
                },
                tables={"events": events_table_symbol},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.symbol, expected.symbol)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_person_table_aliased(self):
        expr = parse_select("select event, e.pdi.person.id from events e")
        resolve_symbols(expr)
        events_table_symbol = ast.TableSymbol(table=database.events)
        events_table_alias_symbol = ast.TableAliasSymbol(table=events_table_symbol, name="e")
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    symbol=ast.FieldSymbol(name="event", table=events_table_alias_symbol),
                ),
                ast.Field(
                    chain=["e", "pdi", "person", "id"],
                    symbol=ast.FieldSymbol(
                        name="id",
                        table=ast.LazyTableSymbol(
                            table=ast.LazyTableSymbol(
                                table=events_table_alias_symbol, field="pdi", joined_table=database.events.pdi
                            ),
                            field="person",
                            joined_table=database.events.pdi.table.person,
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], symbol=events_table_symbol),
                alias="e",
                symbol=events_table_alias_symbol,
            ),
            symbol=ast.SelectQuerySymbol(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldSymbol(name="event", table=events_table_alias_symbol),
                    "id": ast.FieldSymbol(
                        name="id",
                        table=ast.LazyTableSymbol(
                            table=ast.LazyTableSymbol(
                                table=events_table_alias_symbol, field="pdi", joined_table=database.events.pdi
                            ),
                            field="person",
                            joined_table=database.events.pdi.table.person,
                        ),
                    ),
                },
                tables={"e": events_table_alias_symbol},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.symbol, expected.symbol)
        self.assertEqual(expr, expected)


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
