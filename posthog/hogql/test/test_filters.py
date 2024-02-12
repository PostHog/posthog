from typing import Dict, Any

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.visitor import clear_locations
from posthog.schema import (
    HogQLFilters,
    EventPropertyFilter,
    PersonPropertyFilter,
    DateRange,
)
from posthog.test.base import BaseTest


class TestFilters(BaseTest):
    maxDiff = None

    def _parse_expr(self, expr: str, placeholders: Dict[str, Any] = None):
        return clear_locations(parse_expr(expr, placeholders=placeholders))

    def _parse_select(self, select: str, placeholders: Dict[str, Any] = None):
        return clear_locations(parse_select(select, placeholders=placeholders))

    def _print_ast(self, node: ast.Expr):
        return print_ast(
            node,
            dialect="hogql",
            context=HogQLContext(team_id=self.team.pk, enable_select_queries=True),
        )

    def test_replace_filters(self):
        select = replace_filters(self._parse_select("SELECT event FROM events"), HogQLFilters(), self.team)
        self.assertEqual(self._print_ast(select), "SELECT event FROM events LIMIT 10000")

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(),
            self.team,
        )
        self.assertEqual(self._print_ast(select), "SELECT event FROM events WHERE true LIMIT 10000")

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(dateRange=DateRange(date_from="2020-02-02")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            "SELECT event FROM events WHERE greaterOrEquals(timestamp, toDateTime('2020-02-02 00:00:00.000000')) LIMIT 10000",
        )

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(dateRange=DateRange(date_to="2020-02-02")),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            "SELECT event FROM events WHERE less(timestamp, toDateTime('2020-02-02 00:00:00.000000')) LIMIT 10000",
        )

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(
                properties=[EventPropertyFilter(key="random_uuid", operator="exact", value="123", type="event")]
            ),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            "SELECT event FROM events WHERE equals(properties.random_uuid, '123') LIMIT 10000",
        )

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(
                properties=[PersonPropertyFilter(key="random_uuid", operator="exact", value="123", type="person")]
            ),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            "SELECT event FROM events WHERE equals(person.properties.random_uuid, '123') LIMIT 10000",
        )

        select = replace_filters(
            self._parse_select("SELECT event FROM events where {filters}"),
            HogQLFilters(
                properties=[
                    EventPropertyFilter(key="random_uuid", operator="exact", value="123", type="event"),
                    PersonPropertyFilter(key="random_uuid", operator="exact", value="123", type="person"),
                ]
            ),
            self.team,
        )
        self.assertEqual(
            self._print_ast(select),
            "SELECT event FROM events WHERE and(equals(properties.random_uuid, '123'), equals(person.properties.random_uuid, '123')) LIMIT 10000",
        )
