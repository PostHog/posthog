from typing import Union, Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.session_where_clause_extractor import SessionWhereClauseExtractor
from posthog.hogql.database.schema.util.where_clause_visitor import PassThroughHogQLASTVisitor
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select, parse_expr
from posthog.hogql.printer import prepare_ast_for_printing
from posthog.test.base import ClickhouseTestMixin, APIBaseTest


def f(s: Union[str, ast.Expr], placeholders: Optional[dict[str, ast.Expr]] = None) -> Union[ast.Expr, None]:
    if s is None:
        return None
    if isinstance(s, str):
        expr = parse_expr(s, placeholders=placeholders)
    else:
        expr = s
    return PassThroughHogQLASTVisitor().visit(expr)


class TestSessionTimestampInliner:
    def test_handles_select_with_no_where_claus(self):
        inliner = SessionWhereClauseExtractor()
        inner_where = inliner.get_inner_where(parse_select("SELECT * FROM sessions"))
        assert inner_where is None

    def test_handles_select_with_eq(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(inliner.get_inner_where(parse_select("SELECT * FROM sessions WHERE min_timestamp = '2021-01-01'")))
        expected = f(
            "((sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-01') AND ((sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01')"
        )
        assert expected == actual

    def test_handles_select_with_eq_flipped(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(inliner.get_inner_where(parse_select("SELECT * FROM sessions WHERE '2021-01-01' = min_timestamp")))
        expected = f(
            "((sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-01') AND ((sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01')"
        )
        assert expected == actual

    def test_handles_select_with_simple_gt(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(inliner.get_inner_where(parse_select("SELECT * FROM sessions WHERE min_timestamp > '2021-01-01'")))
        expected = f("((sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01')")
        assert expected == actual

    def test_handles_select_with_simple_gte(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(inliner.get_inner_where(parse_select("SELECT * FROM sessions WHERE min_timestamp >= '2021-01-01'")))
        expected = f("((sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01')")
        assert expected == actual

    def test_handles_select_with_simple_lt(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(inliner.get_inner_where(parse_select("SELECT * FROM sessions WHERE min_timestamp < '2021-01-01'")))
        expected = f("((sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-01')")
        assert expected == actual

    def test_handles_select_with_simple_lte(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(inliner.get_inner_where(parse_select("SELECT * FROM sessions WHERE min_timestamp <= '2021-01-01'")))
        expected = f("((sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-01')")
        assert expected == actual

    def test_select_with_placeholder(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(
            inliner.get_inner_where(
                parse_select(
                    "SELECT * FROM sessions WHERE min_timestamp > {timestamp}",
                    placeholders={"timestamp": ast.Constant(value="2021-01-01")},
                )
            )
        )
        expected = f("((sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01')")
        assert expected == actual

    def test_unrelated_equals(self):
        inliner = SessionWhereClauseExtractor()
        actual = inliner.get_inner_where(
            parse_select("SELECT * FROM sessions WHERE initial_utm_campaign = initial_utm_source")
        )
        assert actual is None

    def test_timestamp_and(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(
            inliner.get_inner_where(
                parse_select(
                    "SELECT * FROM sessions WHERE and(min_timestamp >= '2021-01-01', min_timestamp <= '2021-01-03')"
                )
            )
        )
        expected = f(
            "((sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01') AND ((sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-03')"
        )
        assert expected == actual

    def test_timestamp_or(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(
            inliner.get_inner_where(
                parse_select(
                    "SELECT * FROM sessions WHERE and(min_timestamp <= '2021-01-01', min_timestamp >= '2021-01-03')"
                )
            )
        )
        expected = f(
            "((sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-01') AND ((sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-03')"
        )
        assert expected == actual

    def test_unrelated_function(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(inliner.get_inner_where(parse_select("SELECT * FROM sessions WHERE like('a', 'b')")))
        assert actual is None

    def test_timestamp_unrelated_function(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(
            inliner.get_inner_where(parse_select("SELECT * FROM sessions WHERE like(toString(min_timestamp), 'b')"))
        )
        assert actual is None

    def test_timestamp_unrelated_function_timestamp(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(
            inliner.get_inner_where(parse_select("SELECT * FROM sessions WHERE like(toString(min_timestamp), 'b')"))
        )
        assert actual is None

    def test_ambiguous_or(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(
            inliner.get_inner_where(
                parse_select(
                    "SELECT * FROM sessions WHERE or(min_timestamp > '2021-01-03', like(toString(min_timestamp), 'b'))"
                )
            )
        )
        assert actual is None

    def test_ambiguous_and(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(
            inliner.get_inner_where(
                parse_select(
                    "SELECT * FROM sessions WHERE and(min_timestamp > '2021-01-03', like(toString(min_timestamp), 'b'))"
                )
            )
        )
        assert actual == f("(sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-03'")

    def test_join(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(
            inliner.get_inner_where(
                parse_select(
                    "SELECT * FROM events JOIN sessions ON events.session_id = sessions.session_id WHERE min_timestamp > '2021-01-03'"
                )
            )
        )
        expected = f("((sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-03')")
        assert expected == actual

    def test_join_using_events_timestamp_filter(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(
            inliner.get_inner_where(
                parse_select(
                    "SELECT * FROM events JOIN sessions ON events.session_id = sessions.session_id WHERE timestamp > '2021-01-03'"
                )
            )
        )
        expected = f("((sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-03')")
        assert expected == actual

    def test_minus(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(inliner.get_inner_where(parse_select("SELECT * FROM sessions WHERE min_timestamp >= today() - 2")))
        expected = f("((sessions.min_timestamp + toIntervalDay(3)) >= (today() - 2))")
        assert expected == actual

    def test_minus_function(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(
            inliner.get_inner_where(parse_select("SELECT * FROM sessions WHERE min_timestamp >= minus(today() , 2)"))
        )
        expected = f("((sessions.min_timestamp + toIntervalDay(3)) >= minus(today(), 2))")
        assert expected == actual

    def test_real_example(self):
        inliner = SessionWhereClauseExtractor()
        actual = f(
            inliner.get_inner_where(
                parse_select(
                    "SELECT * FROM events JOIN sessions ON events.session_id = sessions.session_id WHERE event = '$pageview' AND toTimeZone(timestamp, 'US/Pacific') >= toDateTime('2024-03-12 00:00:00', 'US/Pacific') AND toTimeZone(timestamp, 'US/Pacific') <= toDateTime('2024-03-19 23:59:59', 'US/Pacific')"
                )
            )
        )
        expected = f(
            "(toTimeZone(sessions.min_timestamp, 'US/Pacific') + toIntervalDay(3)) >= toDateTime('2024-03-12 00:00:00', 'US/Pacific') AND (toTimeZone(sessions.min_timestamp, 'US/Pacific') - toIntervalDay(3)) <= toDateTime('2024-03-19 23:59:59', 'US/Pacific') "
        )
        assert expected == actual


class TestSessionsQueriesHogQLToClickhouse(ClickhouseTestMixin, APIBaseTest):
    def print_query(self, query: str) -> ast.Expr:
        team = self.team
        modifiers = create_default_modifiers_for_team(team)
        context = HogQLContext(
            team_id=team.pk,
            team=team,
            enable_select_queries=True,
            modifiers=modifiers,
        )
        return prepare_ast_for_printing(node=parse_select(query), context=context, dialect="clickhouse")

    def test_select_with_timestamp(self):
        actual = self.print_query("SELECT * FROM sessions WHERE min_timestamp > '2021-01-01'")
        expected = ""
        assert expected == actual
