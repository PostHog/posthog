from typing import Union, Optional, Dict

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.session_where_clause_extractor import SessionMinTimestampWhereClauseExtractor
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select, parse_expr
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.visitor import clone_expr
from posthog.test.base import ClickhouseTestMixin, APIBaseTest


def f(s: Union[str, ast.Expr, None], placeholders: Optional[dict[str, ast.Expr]] = None) -> Union[ast.Expr, None]:
    if s is None:
        return None
    if isinstance(s, str):
        expr = parse_expr(s, placeholders=placeholders)
    else:
        expr = s
    return clone_expr(expr, clear_types=True, clear_locations=True)


def parse(
    s: str,
    placeholders: Optional[Dict[str, ast.Expr]] = None,
) -> ast.SelectQuery:
    parsed = parse_select(s, placeholders=placeholders)
    assert isinstance(parsed, ast.SelectQuery)
    return parsed


class TestSessionTimestampInliner(ClickhouseTestMixin, APIBaseTest):
    @property
    def inliner(self):
        team = self.team
        modifiers = create_default_modifiers_for_team(team)
        context = HogQLContext(
            team_id=team.pk,
            team=team,
            enable_select_queries=True,
            modifiers=modifiers,
        )
        return SessionMinTimestampWhereClauseExtractor(context)

    def test_handles_select_with_no_where_claus(self):
        inner_where = self.inliner.get_inner_where(parse("SELECT * FROM sessions"))
        assert inner_where is None

    def test_handles_select_with_eq(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE min_timestamp = '2021-01-01'")))
        expected = f(
            "((raw_sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-01') AND ((raw_sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01')"
        )
        assert expected == actual

    def test_handles_select_with_eq_flipped(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE '2021-01-01' = min_timestamp")))
        expected = f(
            "((raw_sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-01') AND ((raw_sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01')"
        )
        assert expected == actual

    def test_handles_select_with_simple_gt(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE min_timestamp > '2021-01-01'")))
        expected = f("((raw_sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01')")
        assert expected == actual

    def test_handles_select_with_simple_gte(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE min_timestamp >= '2021-01-01'")))
        expected = f("((raw_sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01')")
        assert expected == actual

    def test_handles_select_with_simple_lt(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE min_timestamp < '2021-01-01'")))
        expected = f("((raw_sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-01')")
        assert expected == actual

    def test_handles_select_with_simple_lte(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE min_timestamp <= '2021-01-01'")))
        expected = f("((raw_sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-01')")
        assert expected == actual

    def test_select_with_placeholder(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM sessions WHERE min_timestamp > {timestamp}",
                    placeholders={"timestamp": ast.Constant(value="2021-01-01")},
                )
            )
        )
        expected = f("((raw_sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01')")
        assert expected == actual

    def test_unrelated_equals(self):
        actual = self.inliner.get_inner_where(
            parse("SELECT * FROM sessions WHERE initial_utm_campaign = initial_utm_source")
        )
        assert actual is None

    def test_timestamp_and(self):
        actual = f(
            self.inliner.get_inner_where(
                parse("SELECT * FROM sessions WHERE and(min_timestamp >= '2021-01-01', min_timestamp <= '2021-01-03')")
            )
        )
        expected = f(
            "((raw_sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-01') AND ((raw_sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-03')"
        )
        assert expected == actual

    def test_timestamp_or(self):
        actual = f(
            self.inliner.get_inner_where(
                parse("SELECT * FROM sessions WHERE and(min_timestamp <= '2021-01-01', min_timestamp >= '2021-01-03')")
            )
        )
        expected = f(
            "((raw_sessions.min_timestamp - toIntervalDay(3)) <= '2021-01-01') AND ((raw_sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-03')"
        )
        assert expected == actual

    def test_unrelated_function(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE like('a', 'b')")))
        assert actual is None

    def test_timestamp_unrelated_function(self):
        actual = f(
            self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE like(toString(min_timestamp), 'b')"))
        )
        assert actual is None

    def test_timestamp_unrelated_function_timestamp(self):
        actual = f(
            self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE like(toString(min_timestamp), 'b')"))
        )
        assert actual is None

    def test_ambiguous_or(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM sessions WHERE or(min_timestamp > '2021-01-03', like(toString(min_timestamp), 'b'))"
                )
            )
        )
        assert actual is None

    def test_ambiguous_and(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM sessions WHERE and(min_timestamp > '2021-01-03', like(toString(min_timestamp), 'b'))"
                )
            )
        )
        assert actual == f("(raw_sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-03'")

    def test_join(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM events JOIN sessions ON events.session_id = raw_sessions.session_id WHERE min_timestamp > '2021-01-03'"
                )
            )
        )
        expected = f("((raw_sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-03')")
        assert expected == actual

    def test_join_using_events_timestamp_filter(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM events JOIN sessions ON events.session_id = raw_sessions.session_id WHERE timestamp > '2021-01-03'"
                )
            )
        )
        expected = f("((raw_sessions.min_timestamp + toIntervalDay(3)) >= '2021-01-03')")
        assert expected == actual

    def test_minus(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE min_timestamp >= today() - 2")))
        expected = f("((raw_sessions.min_timestamp + toIntervalDay(3)) >= (today() - 2))")
        assert expected == actual

    def test_minus_function(self):
        actual = f(
            self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE min_timestamp >= minus(today() , 2)"))
        )
        expected = f("((raw_sessions.min_timestamp + toIntervalDay(3)) >= minus(today(), 2))")
        assert expected == actual

    def test_real_example(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM events JOIN sessions ON events.session_id = raw_sessions.session_id WHERE event = '$pageview' AND toTimeZone(timestamp, 'US/Pacific') >= toDateTime('2024-03-12 00:00:00', 'US/Pacific') AND toTimeZone(timestamp, 'US/Pacific') <= toDateTime('2024-03-19 23:59:59', 'US/Pacific')"
                )
            )
        )
        expected = f(
            "(toTimeZone(raw_sessions.min_timestamp, 'US/Pacific') + toIntervalDay(3)) >= toDateTime('2024-03-12 00:00:00', 'US/Pacific') AND (toTimeZone(raw_sessions.min_timestamp, 'US/Pacific') - toIntervalDay(3)) <= toDateTime('2024-03-19 23:59:59', 'US/Pacific') "
        )
        assert expected == actual

    def test_collapse_and(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM sesions WHERE event = '$pageview' AND (TRUE AND (TRUE AND TRUE AND (timestamp >= '2024-03-12' AND TRUE)))"
                )
            )
        )
        expected = f("(raw_sessions.min_timestamp + toIntervalDay(3)) >= '2024-03-12'")
        assert expected == actual


class TestSessionsQueriesHogQLToClickhouse(ClickhouseTestMixin, APIBaseTest):
    def print_query(self, query: str) -> str:
        team = self.team
        modifiers = create_default_modifiers_for_team(team)
        context = HogQLContext(
            team_id=team.pk,
            team=team,
            enable_select_queries=True,
            modifiers=modifiers,
        )
        prepared_ast = prepare_ast_for_printing(node=parse(query), context=context, dialect="clickhouse")
        pretty = print_prepared_ast(prepared_ast, context=context, dialect="clickhouse", pretty=True)
        return pretty

    def test_select_with_timestamp(self):
        actual = self.print_query("SELECT session_id FROM sessions WHERE min_timestamp > '2021-01-01'")
        expected = f"""SELECT
    sessions.session_id AS session_id
FROM
    (SELECT
        sessions.session_id AS session_id,
        min(sessions.min_timestamp) AS min_timestamp
    FROM
        sessions
    WHERE
        and(equals(sessions.team_id, {self.team.id}), ifNull(greaterOrEquals(plus(toTimeZone(sessions.min_timestamp, %(hogql_val_0)s), toIntervalDay(3)), %(hogql_val_1)s), 0))
    GROUP BY
        sessions.session_id,
        sessions.session_id) AS sessions
WHERE
    ifNull(greater(toTimeZone(sessions.min_timestamp, %(hogql_val_2)s), %(hogql_val_3)s), 0)
LIMIT 10000"""
        assert expected == actual

    def test_join_with_events(self):
        actual = self.print_query(
            """
SELECT
    sessions.session_id,
    uniq(uuid)
FROM events
JOIN sessions
ON events.$session_id = sessions.session_id
WHERE events.timestamp > '2021-01-01'
GROUP BY sessions.session_id
"""
        )
        expected = f"""SELECT
    sessions.session_id AS session_id,
    uniq(events.uuid)
FROM
    events
    JOIN (SELECT
        sessions.session_id AS session_id
    FROM
        sessions
    WHERE
        and(equals(sessions.team_id, {self.team.id}), ifNull(greaterOrEquals(plus(toTimeZone(sessions.min_timestamp, %(hogql_val_0)s), toIntervalDay(3)), %(hogql_val_1)s), 0))
    GROUP BY
        sessions.session_id,
        sessions.session_id) AS sessions ON equals(events.`$session_id`, sessions.session_id)
WHERE
    and(equals(events.team_id, {self.team.id}), greater(toTimeZone(events.timestamp, %(hogql_val_2)s), %(hogql_val_3)s))
GROUP BY
    sessions.session_id
LIMIT 10000"""
        assert expected == actual
