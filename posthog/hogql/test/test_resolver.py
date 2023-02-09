from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_symbols
from posthog.test.base import BaseTest


class TestResolver(BaseTest):
    def test_resolve_events_table(self):
        expr = parse_select("SELECT event, events.timestamp FROM events WHERE events.event = 'test'")
        resolve_symbols(expr)

        events_table_symbol = ast.TableSymbol(name="events", table_name="events")
        event_field_symbol = ast.FieldSymbol(name="event", table=events_table_symbol)
        timestamp_field_symbol = ast.FieldSymbol(name="timestamp", table=events_table_symbol)
        select_query_symbol = ast.SelectQuerySymbol(
            name="",
            symbols={},
            tables={"events": events_table_symbol},
        )

        self.assertEqual(
            expr,
            ast.SelectQuery(
                select=[
                    ast.Field(chain=["event"], symbol=event_field_symbol),
                    ast.Field(chain=["events", "timestamp"], symbol=timestamp_field_symbol),
                ],
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=["events"], symbol=events_table_symbol),
                    alias="events",
                ),
                where=ast.CompareOperation(
                    left=ast.Field(chain=["events", "event"], symbol=event_field_symbol),
                    op=ast.CompareOperationType.Eq,
                    right=ast.Constant(value="test"),
                ),
                symbol=select_query_symbol,
            ),
        )

    def test_resolve_events_table_alias(self):
        expr = parse_select("SELECT event, e.timestamp FROM events e WHERE e.event = 'test'")
        resolve_symbols(expr)

        events_table_symbol = ast.TableSymbol(name="e", table_name="events")
        event_field_symbol = ast.FieldSymbol(name="event", table=events_table_symbol)
        timestamp_field_symbol = ast.FieldSymbol(name="timestamp", table=events_table_symbol)
        select_query_symbol = ast.SelectQuerySymbol(
            name="",
            symbols={},
            tables={"e": events_table_symbol},
        )

        self.assertEqual(
            expr,
            ast.SelectQuery(
                select=[
                    ast.Field(chain=["event"], symbol=event_field_symbol),
                    ast.Field(chain=["e", "timestamp"], symbol=timestamp_field_symbol),
                ],
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=["events"], symbol=events_table_symbol),
                    alias="e",
                ),
                where=ast.CompareOperation(
                    left=ast.Field(chain=["e", "event"], symbol=event_field_symbol),
                    op=ast.CompareOperationType.Eq,
                    right=ast.Constant(value="test"),
                ),
                symbol=select_query_symbol,
            ),
        )


# "with 2 as a select 1 as a" -> "Different expressions with the same alias a:"
# "with 2 as b, 3 as c select (select 1 as b) as a, b, c" -> "Different expressions with the same alias b:"


# "select a, b, e.c from (select 1 as a, 2 as b, 3 as c) as e" -> 1, 2, 3
