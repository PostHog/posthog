from posthog.hogql import ast
from posthog.hogql.database import database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_symbols
from posthog.hogql.transforms import resolve_lazy_tables
from posthog.test.base import BaseTest


class TestTransforms(BaseTest):
    def test_resolve_lazy_tables(self):
        expr = parse_select("select event, pdi.person_id from events")
        resolve_symbols(expr)
        resolve_lazy_tables(expr)
        events_table_symbol = ast.TableSymbol(table=database.events)
        next_join = database.events.pdi.join_function("events", "events__pdi", ["person_id"])
        # resolve_symbols(next_join, expr.symbol)

        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    symbol=ast.FieldSymbol(name="event", table=events_table_symbol),
                ),
                ast.Field(
                    chain=["person_id"],
                    symbol=ast.FieldSymbol(
                        name="person_id",
                        table=next_join.table.symbol,
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], symbol=events_table_symbol),
                symbol=events_table_symbol,
                next_join=next_join,
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
