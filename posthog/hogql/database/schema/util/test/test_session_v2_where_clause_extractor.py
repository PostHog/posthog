from datetime import UTC, datetime
from typing import Any, Optional, Union

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import SessionTableVersion

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.where_clause_extractor import SessionMinTimestampWhereClauseExtractorV2
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.visitor import clone_expr

from posthog.models import EventDefinition


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
    placeholders: Optional[dict[str, ast.Expr]] = None,
) -> ast.SelectQuery | ast.SelectSetQuery:
    parsed = parse_select(s, placeholders=placeholders)
    return parsed


@pytest.mark.usefixtures("unittest_snapshot")
class TestSessionWhereClauseExtractorV2(ClickhouseTestMixin, APIBaseTest):
    snapshot: Any

    @property
    def inliner(self):
        team = self.team
        modifiers = create_default_modifiers_for_team(team)
        modifiers.sessionTableVersion = SessionTableVersion.V2
        context = HogQLContext(
            team_id=team.pk,
            team=team,
            enable_select_queries=True,
            modifiers=modifiers,
        )
        return SessionMinTimestampWhereClauseExtractorV2(context)

    def test_handles_select_with_no_where_claus(self):
        inner_where = self.inliner.get_inner_where(parse("SELECT * FROM sessions"))
        assert inner_where is None

    def test_default_bound_with_limit(self):
        EventDefinition.objects.create(
            team=self.team,
            name="$pageview",
            last_seen_at=datetime(2099, 1, 15, tzinfo=UTC),
        )
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions LIMIT 10")))
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= (toDateTime('2099-01-15 00:00:00') - toIntervalDay(30))"
        )
        assert expected == actual

    def test_no_default_bound_with_limit_and_order_by(self):
        actual = self.inliner.get_inner_where(parse("SELECT * FROM sessions ORDER BY $start_timestamp LIMIT 10"))
        assert actual is None

    def test_no_default_bound_with_limit_and_order_by_non_timestamp(self):
        actual = self.inliner.get_inner_where(parse("SELECT * FROM sessions ORDER BY $channel_type LIMIT 10"))
        assert actual is None

    def test_no_default_bound_with_limit_and_unrelated_where(self):
        actual = self.inliner.get_inner_where(
            parse("SELECT * FROM sessions WHERE $initial_utm_campaign = $initial_utm_source LIMIT 10")
        )
        assert actual is None

    def test_no_default_bound_with_limit_when_not_select_star(self):
        actual = self.inliner.get_inner_where(parse("SELECT event FROM sessions LIMIT 10"))
        assert actual is None

    def assert_limit_bound_edge_case(self, query: str, expected: str):
        EventDefinition.objects.create(
            team=self.team,
            name="$pageview",
            last_seen_at=datetime(2099, 1, 15, tzinfo=UTC),
        )
        actual = f(self.inliner.get_inner_where(parse(query)))
        assert actual == f(expected)

    def test_limit_bound_where_wins(self):
        self.assert_limit_bound_edge_case(
            "SELECT * FROM sessions WHERE $start_timestamp > '2021-01-01' LIMIT 10",
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2021-01-01' - toIntervalDay(3))",
        )

    def test_limit_bound_with_offset(self):
        self.assert_limit_bound_edge_case(
            "SELECT * FROM sessions LIMIT 10 OFFSET 5",
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= (toDateTime('2099-01-15 00:00:00') - toIntervalDay(30))",
        )

    def test_no_limit_bound_with_group_by(self):
        actual = self.inliner.get_inner_where(parse("SELECT event, count() FROM sessions GROUP BY event LIMIT 10"))
        assert actual is None

    def test_handles_select_with_eq(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp = '2021-01-01'")))
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2021-01-01' - toIntervalDay(3)) AND fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= ('2021-01-01' + toIntervalDay(3))"
        )
        assert expected == actual

    def test_handles_select_with_eq_flipped(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE '2021-01-01' = $start_timestamp")))
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2021-01-01' - toIntervalDay(3)) AND fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= ('2021-01-01' + toIntervalDay(3))"
        )
        assert expected == actual

    def test_handles_select_with_simple_gt(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp > '2021-01-01'")))
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2021-01-01' - toIntervalDay(3))"
        )
        assert expected == actual

    def test_handles_select_with_simple_gte(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp >= '2021-01-01'")))
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2021-01-01' - toIntervalDay(3))"
        )
        assert expected == actual

    def test_handles_select_with_simple_lt(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp < '2021-01-01'")))
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= ('2021-01-01' + toIntervalDay(3))"
        )
        assert expected == actual

    def test_handles_select_with_simple_lte(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp <= '2021-01-01'")))
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= ('2021-01-01' + toIntervalDay(3))"
        )
        assert expected == actual

    def test_select_with_placeholder(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM sessions WHERE $start_timestamp > {timestamp}",
                    placeholders={"timestamp": ast.Constant(value="2021-01-01")},
                )
            )
        )
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2021-01-01' - toIntervalDay(3))"
        )
        assert expected == actual

    def test_unrelated_equals(self):
        actual = self.inliner.get_inner_where(
            parse("SELECT * FROM sessions WHERE $initial_utm_campaign = $initial_utm_source")
        )
        assert actual is None

    def test_timestamp_and(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM sessions WHERE and($start_timestamp >= '2021-01-01', $start_timestamp <= '2021-01-03')"
                )
            )
        )
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2021-01-01' - toIntervalDay(3)) AND fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= ('2021-01-03' + toIntervalDay(3))"
        )
        assert expected == actual

    def test_timestamp_or(self):
        actual = f(
            self.inliner.get_inner_where(
                parse("SELECT * FROM sessions WHERE and(min_timestamp <= '2021-01-01', min_timestamp >= '2021-01-03')")
            )
        )
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= ('2021-01-01' + toIntervalDay(3)) AND fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2021-01-03' - toIntervalDay(3))"
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
                    "SELECT * FROM sessions WHERE or($start_timestamp > '2021-01-03', like(toString($start_timestamp), 'b'))"
                )
            )
        )
        assert actual is None

    def test_ambiguous_and(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM sessions WHERE and($start_timestamp > '2021-01-03', like(toString($start_timestamp), 'b'))"
                )
            )
        )
        assert actual == f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2021-01-03' - toIntervalDay(3))"
        )

    def test_join(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM events JOIN sessions ON events.session_id = sessions.session_id WHERE $start_timestamp > '2021-01-03'"
                )
            )
        )
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2021-01-03' - toIntervalDay(3))"
        )
        assert expected == actual

    def test_join_using_events_timestamp_filter(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM events JOIN sessions ON events.session_id = sessions.session_id WHERE timestamp > '2021-01-03'"
                )
            )
        )
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2021-01-03' - toIntervalDay(3))"
        )
        assert expected == actual

    def test_minus(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp >= today() - 2")))
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ((today() - 2) - toIntervalDay(3))"
        )
        assert expected == actual

    def test_minus_function(self):
        actual = f(
            self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp >= minus(today() , 2)"))
        )
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= (minus(today(), 2) - toIntervalDay(3))"
        )
        assert expected == actual

    def test_less_function(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE less($start_timestamp, today())")))
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= (today() + toIntervalDay(3))"
        )
        assert expected == actual

    def test_less_function_second_arg(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE less(today(), $start_timestamp)")))
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= (today() - toIntervalDay(3))"
        )
        assert expected == actual

    def test_subquery_args(self):
        actual = f(
            self.inliner.get_inner_where(
                parse("SELECT * FROM sessions WHERE true = (select false) and less(today(), min_timestamp)")
            )
        )
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= (today() - toIntervalDay(3))"
        )
        assert expected == actual

    def test_real_example(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM events JOIN sessions ON events.session_id = sessions.session_id WHERE event = '$pageview' AND toTimeZone(timestamp, 'US/Pacific') >= toDateTime('2024-03-12 00:00:00', 'US/Pacific') AND toTimeZone(timestamp, 'US/Pacific') <= toDateTime('2024-03-19 23:59:59', 'US/Pacific')"
                )
            )
        )
        expected = f(
            "toTimeZone(fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), 'US/Pacific') >= (toDateTime('2024-03-12 00:00:00', 'US/Pacific') - toIntervalDay(3)) AND toTimeZone(fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), 'US/Pacific') <= (toDateTime('2024-03-19 23:59:59', 'US/Pacific') + toIntervalDay(3))"
        )
        assert expected == actual

    def test_collapse_and(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM sessions WHERE event = '$pageview' AND (TRUE AND (TRUE AND TRUE AND (timestamp >= '2024-03-12' AND TRUE)))"
                )
            )
        )
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2024-03-12' - toIntervalDay(3))"
        )
        assert expected == actual

    def test_select_query(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM sessions WHERE timestamp = (SELECT max(timestamp) FROM events WHERE event = '$pageview')"
                )
            )
        )
        assert actual is None

    def test_breakdown_subquery(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    f"""
SELECT
            count(DISTINCT e.$session_id) AS total,
            toStartOfDay(timestamp) AS day_start,
            multiIf(and(greaterOrEquals(session.$session_duration, 2.0), less(session.$session_duration, 4.5)), '[2.0,4.5]', and(greaterOrEquals(session.$session_duration, 4.5), less(session.$session_duration, 27.0)), '[4.5,27.0]', and(greaterOrEquals(session.$session_duration, 27.0), less(session.$session_duration, 44.0)), '[27.0,44.0]', and(greaterOrEquals(session.$session_duration, 44.0), less(session.$session_duration, 48.0)), '[44.0,48.0]', and(greaterOrEquals(session.$session_duration, 48.0), less(session.$session_duration, 57.5)), '[48.0,57.5]', and(greaterOrEquals(session.$session_duration, 57.5), less(session.$session_duration, 61.0)), '[57.5,61.0]', and(greaterOrEquals(session.$session_duration, 61.0), less(session.$session_duration, 74.0)), '[61.0,74.0]', and(greaterOrEquals(session.$session_duration, 74.0), less(session.$session_duration, 90.0)), '[74.0,90.0]', and(greaterOrEquals(session.$session_duration, 90.0), less(session.$session_duration, 98.5)), '[90.0,98.5]', and(greaterOrEquals(session.$session_duration, 98.5), less(session.$session_duration, 167.01)), '[98.5,167.01]', '["",""]') AS breakdown_value
        FROM
            events AS e
        WHERE
            and(greaterOrEquals(timestamp, toStartOfDay(assumeNotNull(toDateTime('2024-04-13 00:00:00')))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-04-20 23:59:59'))), equals(event, '$pageview'), in(person_id, (SELECT
                        person_id
                    FROM
                        raw_cohort_people
                    WHERE
                        and(equals(cohort_id, 2), equals(version, 0)))))
        GROUP BY
            day_start,
            breakdown_value
                """
                )
            )
        )
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= (toStartOfDay(assumeNotNull(toDateTime('2024-04-13 00:00:00'))) - toIntervalDay(3)) AND fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= (assumeNotNull(toDateTime('2024-04-20 23:59:59')) + toIntervalDay(3))"
        )
        assert expected == actual

    def test_not_like(self):
        # based on a bug here: https://posthog.slack.com/archives/C05LJK1N3CP/p1719916566421079
        where = ast.And(
            exprs=[
                ast.CompareOperation(
                    left=ast.Field(chain=["event"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value="$pageview"),
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=["timestamp"]),
                    op=ast.CompareOperationOp.GtEq,
                    right=ast.Constant(value="2024-03-12"),
                ),
                ast.And(
                    exprs=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["host"]),
                            op=ast.CompareOperationOp.NotILike,
                            right=ast.Constant(value="localhost:3000"),
                        ),
                        ast.CompareOperation(
                            left=ast.Field(chain=["host"]),
                            op=ast.CompareOperationOp.NotILike,
                            right=ast.Constant(value="localhost:3001"),
                        ),
                    ]
                ),
            ]
        )
        select = ast.SelectQuery(select=[], where=where)
        actual = f(self.inliner.get_inner_where(select))
        expected = f(
            "fromUnixTimestamp(intDiv(_toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= ('2024-03-12' - toIntervalDay(3))"
        )
        assert expected == actual

    def test_handles_select_set_query_in_comparison(self):
        select_set_query = ast.SelectSetQuery(
            initial_select_query=ast.SelectQuery(select=[ast.Constant(value="2021-01-01")]),
            subsequent_select_queries=[
                ast.SelectSetNode(
                    select_query=ast.SelectQuery(select=[ast.Constant(value="2021-06-01")]),
                    set_operator="UNION ALL",
                )
            ],
        )
        where = ast.CompareOperation(
            left=ast.Field(chain=["$start_timestamp"]),
            op=ast.CompareOperationOp.Gt,
            right=select_set_query,
        )
        select = ast.SelectQuery(select=[], where=where)
        # Should not raise NotImplementedError (regression test for #49867)
        inner_where = self.inliner.get_inner_where(select)
        assert inner_where is None


class TestSessionsV2QueriesHogQLToClickhouse(ClickhouseTestMixin, APIBaseTest):
    def print_query(self, query: str) -> str:
        team = self.team
        modifiers = create_default_modifiers_for_team(team)
        modifiers.sessionTableVersion = SessionTableVersion.V2
        context = HogQLContext(
            team_id=team.pk,
            team=team,
            enable_select_queries=True,
            modifiers=modifiers,
        )
        prepared_ast = prepare_ast_for_printing(node=parse(query), context=context, dialect="clickhouse")
        if prepared_ast is None:
            return ""
        pretty = print_prepared_ast(prepared_ast, context=context, dialect="clickhouse", pretty=True)
        return pretty

    def test_select_with_timestamp(self):
        actual = self.print_query("SELECT session_id FROM sessions WHERE $start_timestamp > '2021-01-01'")
        assert self.generalize_sql(actual) == self.snapshot

    def test_join_with_events(self):
        actual = self.print_query(
            """
SELECT
    sessions.session_id,
    uniq(uuid) as uniq_uuid
FROM events
JOIN sessions
ON events.$session_id = sessions.session_id
WHERE events.timestamp > '2021-01-01'
GROUP BY sessions.session_id
"""
        )
        assert self.generalize_sql(actual) == self.snapshot

    def test_union(self):
        actual = self.print_query(
            """
SELECT 0 as duration
UNION ALL
SELECT events.session.$session_duration as duration
FROM events
WHERE events.timestamp < today()
            """
        )
        assert self.generalize_sql(actual) == self.snapshot

    def test_session_breakdown(self):
        actual = self.print_query(
            """SELECT count(DISTINCT e."$session_id") AS total,
       toStartOfDay(timestamp)         AS day_start,
       multiIf(and(greaterOrEquals(session."$session_duration", 2.0),
                   less(session."$session_duration", 4.5)),
               '[2.0,4.5]',
               and(greaterOrEquals(session."$session_duration", 4.5),
                   less(session."$session_duration", 27.0)),
               '[4.5,27.0]',
               and(greaterOrEquals(session."$session_duration", 27.0),
                   less(session."$session_duration", 44.0)),
               '[27.0,44.0]',
               and(greaterOrEquals(session."$session_duration", 44.0),
                   less(session."$session_duration", 48.0)),
               '[44.0,48.0]',
               and(greaterOrEquals(session."$session_duration", 48.0),
                   less(session."$session_duration", 57.5)),
               '[48.0,57.5]',
               and(greaterOrEquals(session."$session_duration", 57.5),
                   less(session."$session_duration", 61.0)),
               '[57.5,61.0]',
               and(greaterOrEquals(session."$session_duration", 61.0),
                   less(session."$session_duration", 74.0)),
               '[61.0,74.0]',
               and(greaterOrEquals(session."$session_duration", 74.0),
                   less(session."$session_duration", 90.0)),
               '[74.0,90.0]',
               and(greaterOrEquals(session."$session_duration", 90.0),
                   less(session."$session_duration", 98.5)),
               '[90.0,98.5]', and(greaterOrEquals(session."$session_duration", 98.5),
                                  less(session."$session_duration", 167.01)), '[98.5,167.01]',
               '["",""]')              AS breakdown_value
FROM events AS e
WHERE and(greaterOrEquals(timestamp, toStartOfDay(assumeNotNull(toDateTime('2024-04-13 00:00:00')))),
          lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-04-20 23:59:59'))),
          equals(event, '$pageview'), in(person_id, (SELECT person_id
                                                     FROM raw_cohort_people
                                                     WHERE and(equals(cohort_id, 2), equals(version, 0)))))
GROUP BY day_start,
         breakdown_value"""
        )
        assert self.generalize_sql(actual) == self.snapshot

    def test_session_replay_query(self):
        actual = self.print_query(
            """
SELECT
    s.session_id,
    min(s.min_first_timestamp) as start_time
FROM raw_session_replay_events s
WHERE s.session.$entry_pathname = '/home' AND min_first_timestamp >= '2021-01-01:12:34' AND min_first_timestamp < now()
GROUP BY session_id
        """
        )
        assert self.generalize_sql(actual) == self.snapshot

    def test_urls_in_sessions_in_timestamp_query(self):
        actual = self.print_query(
            """
            select
   session_id,
   `$urls`,
   $start_timestamp
from sessions
where `$start_timestamp` >= now() - toIntervalDay(7)
"""
        )
        assert self.generalize_sql(actual) == self.snapshot

    def test_select_query_alias_type_does_not_crash(self):
        # Regression test: queries with aliased subqueries should not crash when
        # the where clause extractor encounters a SelectQueryAliasType (which
        # doesn't have a .table attribute)
        actual = self.print_query(
            """
SELECT
    subquery.session_id
FROM (
    SELECT
        session_id,
        $start_timestamp
    FROM sessions
    WHERE $start_timestamp >= '2024-01-01'
) AS subquery
WHERE subquery.session_id = '0199a58b-fdf2-785c-b6e3-6ba32b2380cf'
"""
        )
        assert self.generalize_sql(actual) == self.snapshot


@pytest.mark.usefixtures("unittest_snapshot")
class TestSessionIdPushdownV2(ClickhouseTestMixin, APIBaseTest):
    # Tests for the sessionIdPushdown modifier — see
    # https://github.com/PostHog/query-performance-analysis/blob/main/analysis/2026-04-17-experiment-sessions-oom.md

    snapshot: Any

    def print_query(self, query: str, pushdown: bool) -> str:
        team = self.team
        modifiers = create_default_modifiers_for_team(team)
        modifiers.sessionTableVersion = SessionTableVersion.V2
        modifiers.sessionIdPushdown = pushdown
        context = HogQLContext(
            team_id=team.pk,
            team=team,
            enable_select_queries=True,
            modifiers=modifiers,
        )
        prepared_ast = prepare_ast_for_printing(node=parse(query), context=context, dialect="clickhouse")
        if prepared_ast is None:
            return ""
        return print_prepared_ast(prepared_ast, context=context, dialect="clickhouse", pretty=True)

    @parameterized.expand([("with_pushdown", True), ("without_pushdown", False)])
    def test_experiment_shape(self, _name: str, pushdown: bool):
        # Mirrors the ExperimentQuery shape: events -> LEFT JOIN sessions filtered by a
        # session-typed property. With the modifier on, the raw_sessions subquery must carry
        # an IN-pushdown on session_id_v7 (printed as `globalIn(...)` or `in(...)` depending
        # on optimizer settings); with it off, it must not.
        query = """
SELECT
    events.$session_id AS sid,
    events.session.$entry_pathname AS entry
FROM events
WHERE events.event = '$pageview'
  AND events.timestamp >= '2026-03-27 00:00:00'
  AND events.timestamp <= '2026-03-31 23:59:59'
  AND events.session.$entry_pathname = '/signup'
"""
        actual = self.print_query(query, pushdown=pushdown)
        normalized = " ".join(actual.split())
        has_in_pushdown = (
            "in(raw_sessions.session_id_v7" in normalized or "globalIn(raw_sessions.session_id_v7" in normalized
        )
        assert has_in_pushdown == pushdown, f"Expected pushdown={pushdown} in:\n{actual}"
        assert self.generalize_sql(actual) == self.snapshot

    def test_pushdown_noop_for_sessions_only_query(self):
        # A standalone sessions query has no events source to push down from — pushdown
        # should not attempt to add anything, and the query should look identical to the
        # pushdown-disabled version.
        query = "SELECT session_id, $entry_pathname FROM sessions WHERE $start_timestamp >= '2026-03-27'"
        with_pushdown = self.print_query(query, pushdown=True)
        without_pushdown = self.print_query(query, pushdown=False)
        assert with_pushdown == without_pushdown

    def test_pushdown_drops_non_events_or_branches(self):
        # An OR between an events predicate and a session-side predicate must not be
        # pushed down: dropping the session-side half would change semantics. So the
        # extracted events-only WHERE is None and pushdown is skipped.
        query = """
SELECT events.$session_id AS sid, events.session.$entry_pathname AS entry
FROM events
WHERE (events.event = '$pageview') OR (events.session.$entry_pathname = '/signup')
"""
        actual = self.print_query(query, pushdown=True)
        normalized = " ".join(actual.split())
        assert "in(raw_sessions.session_id_v7" not in normalized
        assert "globalIn(raw_sessions.session_id_v7" not in normalized
