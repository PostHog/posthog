from typing import Optional, Union

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from inline_snapshot import snapshot

from posthog.schema import SessionTableVersion

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.where_clause_extractor import SessionMinTimestampWhereClauseExtractorV3
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.visitor import clone_expr


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


class TestSessionWhereClauseExtractorV3(ClickhouseTestMixin, APIBaseTest):
    @property
    def inliner(self):
        team = self.team
        modifiers = create_default_modifiers_for_team(team)
        modifiers.sessionTableVersion = SessionTableVersion.V3
        context = HogQLContext(
            team_id=team.pk,
            team=team,
            enable_select_queries=True,
            modifiers=modifiers,
        )
        return SessionMinTimestampWhereClauseExtractorV3(context)

    def test_handles_select_with_no_where_claus(self):
        inner_where = self.inliner.get_inner_where(parse("SELECT * FROM sessions"))
        assert inner_where is None

    def test_handles_select_with_eq(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp = '2021-01-01'")))
        expected = f(
            "raw_sessions_v3.session_timestamp >= ('2021-01-01' - toIntervalDay(3)) AND raw_sessions_v3.session_timestamp <= ('2021-01-01' + toIntervalDay(3))"
        )
        assert expected == actual

    def test_handles_select_with_eq_flipped(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE '2021-01-01' = $start_timestamp")))
        expected = f(
            "raw_sessions_v3.session_timestamp >= ('2021-01-01' - toIntervalDay(3)) AND raw_sessions_v3.session_timestamp <= ('2021-01-01' + toIntervalDay(3))"
        )
        assert expected == actual

    def test_handles_select_with_simple_gt(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp > '2021-01-01'")))
        expected = f("raw_sessions_v3.session_timestamp >= ('2021-01-01' - toIntervalDay(3))")
        assert expected == actual

    def test_handles_select_with_simple_gte(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp >= '2021-01-01'")))
        expected = f("raw_sessions_v3.session_timestamp >= ('2021-01-01' - toIntervalDay(3))")
        assert expected == actual

    def test_handles_select_with_simple_lt(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp < '2021-01-01'")))
        expected = f("raw_sessions_v3.session_timestamp <= ('2021-01-01' + toIntervalDay(3))")
        assert expected == actual

    def test_handles_select_with_simple_lte(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp <= '2021-01-01'")))
        expected = f("raw_sessions_v3.session_timestamp <= ('2021-01-01' + toIntervalDay(3))")
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
        expected = f("raw_sessions_v3.session_timestamp >= ('2021-01-01' - toIntervalDay(3))")
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
            "raw_sessions_v3.session_timestamp >= ('2021-01-01' - toIntervalDay(3)) AND raw_sessions_v3.session_timestamp <= ('2021-01-03' + toIntervalDay(3))"
        )
        assert expected == actual

    def test_timestamp_or(self):
        actual = f(
            self.inliner.get_inner_where(
                parse("SELECT * FROM sessions WHERE and(min_timestamp <= '2021-01-01', min_timestamp >= '2021-01-03')")
            )
        )
        expected = f(
            "raw_sessions_v3.session_timestamp <= ('2021-01-01' + toIntervalDay(3)) AND raw_sessions_v3.session_timestamp >= ('2021-01-03' - toIntervalDay(3))"
        )
        assert expected == actual

    def test_unrelated_function(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE like('a', 'b')")))
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
        assert actual == f("raw_sessions_v3.session_timestamp >= ('2021-01-03' - toIntervalDay(3))")

    def test_join(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM events JOIN sessions ON events.session_id = sessions.session_id WHERE $start_timestamp > '2021-01-03'"
                )
            )
        )
        expected = f("raw_sessions_v3.session_timestamp >= ('2021-01-03' - toIntervalDay(3))")
        assert expected == actual

    def test_join_using_events_timestamp_filter(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    "SELECT * FROM events JOIN sessions ON events.session_id = sessions.session_id WHERE timestamp > '2021-01-03'"
                )
            )
        )
        expected = f("raw_sessions_v3.session_timestamp >= ('2021-01-03' - toIntervalDay(3))")
        assert expected == actual

    def test_minus(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp >= today() - 2")))
        expected = f("raw_sessions_v3.session_timestamp >= ((today() - 2) - toIntervalDay(3))")
        assert expected == actual

    def test_minus_function(self):
        actual = f(
            self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE $start_timestamp >= minus(today() , 2)"))
        )
        expected = f("raw_sessions_v3.session_timestamp >= (minus(today(), 2) - toIntervalDay(3))")
        assert expected == actual

    def test_less_function(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE less($start_timestamp, today())")))
        expected = f("raw_sessions_v3.session_timestamp <= (today() + toIntervalDay(3))")
        assert expected == actual

    def test_less_function_second_arg(self):
        actual = f(self.inliner.get_inner_where(parse("SELECT * FROM sessions WHERE less(today(), $start_timestamp)")))
        expected = f("raw_sessions_v3.session_timestamp >= (today() - toIntervalDay(3))")
        assert expected == actual

    def test_subquery_args(self):
        actual = f(
            self.inliner.get_inner_where(
                parse("SELECT * FROM sessions WHERE true = (select false) and less(today(), min_timestamp)")
            )
        )
        expected = f("raw_sessions_v3.session_timestamp >= (today() - toIntervalDay(3))")
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
            "toTimeZone(raw_sessions_v3.session_timestamp, 'US/Pacific') >= (toDateTime('2024-03-12 00:00:00', 'US/Pacific') - toIntervalDay(3)) AND toTimeZone(raw_sessions_v3.session_timestamp, 'US/Pacific') <= (toDateTime('2024-03-19 23:59:59', 'US/Pacific') + toIntervalDay(3))"
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
        expected = f("raw_sessions_v3.session_timestamp >= ('2024-03-12' - toIntervalDay(3))")
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
            events AS e SAMPLE 1
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
            "raw_sessions_v3.session_timestamp >= (toStartOfDay(assumeNotNull(toDateTime('2024-04-13 00:00:00'))) - toIntervalDay(3)) AND raw_sessions_v3.session_timestamp <= (assumeNotNull(toDateTime('2024-04-20 23:59:59')) + toIntervalDay(3))"
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
        expected = f("raw_sessions_v3.session_timestamp >= ('2024-03-12' - toIntervalDay(3))")
        assert expected == actual

    def test_point_query(self):
        actual = f(
            self.inliner.get_inner_where(
                parse(
                    """
                    SELECT * FROM sessions WHERE session_id = '0199a58b-fdf2-785c-b6e3-6ba32b2380cf'
                    """
                )
            )
        )
        expected = f(
            "raw_sessions_v3.session_timestamp = fromUnixTimestamp64Milli(_toUInt64(bitShiftRight(_toUInt128(toUUID('0199a58b-fdf2-785c-b6e3-6ba32b2380cf')), 80)))"
        )
        assert expected == actual


class TestSessionsV3QueriesHogQLToClickhouse(ClickhouseTestMixin, APIBaseTest):
    def print_query(self, query: str) -> str:
        team = self.team
        modifiers = create_default_modifiers_for_team(team)
        modifiers.sessionTableVersion = SessionTableVersion.V3
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
        assert self.generalize_sql(actual) == snapshot(
            """\
SELECT
    sessions.session_id AS session_id
FROM
    (SELECT
        toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions_v3.session_id_v7, 64), bitShiftRight(raw_sessions_v3.session_id_v7, 64)))) AS session_id,
        min(toTimeZone(raw_sessions_v3.min_timestamp, %(hogql_val_0)s)) AS `$start_timestamp`,
        raw_sessions_v3.session_id_v7 AS session_id_v7
    FROM
        raw_sessions_v3
    WHERE
        and(equals(raw_sessions_v3.team_id, <TEAM_ID>), greaterOrEquals(raw_sessions_v3.session_timestamp, minus(%(hogql_val_1)s, toIntervalDay(3))))
    GROUP BY
        raw_sessions_v3.session_id_v7) AS sessions
WHERE
    ifNull(greater(sessions.`$start_timestamp`, %(hogql_val_2)s), 0)
LIMIT 50000\
"""
        )

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
        assert self.generalize_sql(actual) == snapshot(
            """\
SELECT
    sessions.session_id AS session_id,
    uniq(events.uuid) AS uniq_uuid
FROM
    events
    JOIN (SELECT
        toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions_v3.session_id_v7, 64), bitShiftRight(raw_sessions_v3.session_id_v7, 64)))) AS session_id,
        raw_sessions_v3.session_id_v7 AS session_id_v7
    FROM
        raw_sessions_v3
    WHERE
        and(equals(raw_sessions_v3.team_id, <TEAM_ID>), greaterOrEquals(raw_sessions_v3.session_timestamp, minus(%(hogql_val_0)s, toIntervalDay(3))))
    GROUP BY
        raw_sessions_v3.session_id_v7) AS sessions ON equals(events.`$session_id`, sessions.session_id)
WHERE
    and(equals(events.team_id, <TEAM_ID>), greater(toTimeZone(events.timestamp, %(hogql_val_1)s), %(hogql_val_2)s))
GROUP BY
    sessions.session_id
LIMIT 50000\
"""
        )

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
        assert self.generalize_sql(actual) == snapshot(
            """\
SELECT
    0 AS duration
LIMIT 50000
UNION ALL
SELECT
    events__session.`$session_duration` AS duration
FROM
    events
    LEFT JOIN (SELECT
        dateDiff(%(hogql_val_0)s, min(toTimeZone(raw_sessions_v3.min_timestamp, %(hogql_val_1)s)), max(toTimeZone(raw_sessions_v3.max_timestamp, %(hogql_val_2)s))) AS `$session_duration`,
        raw_sessions_v3.session_id_v7 AS session_id_v7
    FROM
        raw_sessions_v3
    WHERE
        and(equals(raw_sessions_v3.team_id, <TEAM_ID>), lessOrEquals(raw_sessions_v3.session_timestamp, plus(today(), toIntervalDay(3))))
    GROUP BY
        raw_sessions_v3.session_id_v7) AS events__session ON equals(events.`$session_id_uuid`, events__session.session_id_v7)
WHERE
    and(equals(events.team_id, <TEAM_ID>), less(toTimeZone(events.timestamp, %(hogql_val_3)s), today()))
LIMIT 50000\
"""
        )

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
FROM events AS e SAMPLE 1
WHERE and(greaterOrEquals(timestamp, toStartOfDay(assumeNotNull(toDateTime('2024-04-13 00:00:00')))),
          lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-04-20 23:59:59'))),
          equals(event, '$pageview'), in(person_id, (SELECT person_id
                                                     FROM raw_cohort_people
                                                     WHERE and(equals(cohort_id, 2), equals(version, 0)))))
GROUP BY day_start,
         breakdown_value"""
        )
        assert self.generalize_sql(actual) == snapshot(
            """\
SELECT
    count(DISTINCT e.`$session_id`) AS total,
    toStartOfDay(toTimeZone(e.timestamp, %(hogql_val_7)s)) AS day_start,
    multiIf(and(ifNull(greaterOrEquals(e__session.`$session_duration`, 2.0), 0), ifNull(less(e__session.`$session_duration`, 4.5), 0)), %(hogql_val_8)s, and(ifNull(greaterOrEquals(e__session.`$session_duration`, 4.5), 0), ifNull(less(e__session.`$session_duration`, 27.0), 0)), %(hogql_val_9)s, and(ifNull(greaterOrEquals(e__session.`$session_duration`, 27.0), 0), ifNull(less(e__session.`$session_duration`, 44.0), 0)), %(hogql_val_10)s, and(ifNull(greaterOrEquals(e__session.`$session_duration`, 44.0), 0), ifNull(less(e__session.`$session_duration`, 48.0), 0)), %(hogql_val_11)s, and(ifNull(greaterOrEquals(e__session.`$session_duration`, 48.0), 0), ifNull(less(e__session.`$session_duration`, 57.5), 0)), %(hogql_val_12)s, and(ifNull(greaterOrEquals(e__session.`$session_duration`, 57.5), 0), ifNull(less(e__session.`$session_duration`, 61.0), 0)), %(hogql_val_13)s, and(ifNull(greaterOrEquals(e__session.`$session_duration`, 61.0), 0), ifNull(less(e__session.`$session_duration`, 74.0), 0)), %(hogql_val_14)s, and(ifNull(greaterOrEquals(e__session.`$session_duration`, 74.0), 0), ifNull(less(e__session.`$session_duration`, 90.0), 0)), %(hogql_val_15)s, and(ifNull(greaterOrEquals(e__session.`$session_duration`, 90.0), 0), ifNull(less(e__session.`$session_duration`, 98.5), 0)), %(hogql_val_16)s, and(ifNull(greaterOrEquals(e__session.`$session_duration`, 98.5), 0), ifNull(less(e__session.`$session_duration`, 167.01), 0)), %(hogql_val_17)s, %(hogql_val_18)s) AS breakdown_value
FROM
    events AS e SAMPLE 1
    LEFT OUTER JOIN (SELECT
        argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
        person_distinct_id_overrides.distinct_id AS distinct_id
    FROM
        person_distinct_id_overrides
    WHERE
        equals(person_distinct_id_overrides.team_id, <TEAM_ID>)
    GROUP BY
        person_distinct_id_overrides.distinct_id
    HAVING
        ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
    SETTINGS optimize_aggregation_in_order=1) AS e__override ON equals(e.distinct_id, e__override.distinct_id)
    LEFT JOIN (SELECT
        dateDiff(%(hogql_val_0)s, min(toTimeZone(raw_sessions_v3.min_timestamp, %(hogql_val_1)s)), max(toTimeZone(raw_sessions_v3.max_timestamp, %(hogql_val_2)s))) AS `$session_duration`,
        raw_sessions_v3.session_id_v7 AS session_id_v7
    FROM
        raw_sessions_v3
    WHERE
        and(equals(raw_sessions_v3.team_id, <TEAM_ID>), greaterOrEquals(raw_sessions_v3.session_timestamp, minus(toStartOfDay(assumeNotNull(toDateTime(%(hogql_val_3)s, %(hogql_val_4)s))), toIntervalDay(3))), lessOrEquals(raw_sessions_v3.session_timestamp, plus(assumeNotNull(toDateTime(%(hogql_val_5)s, %(hogql_val_6)s)), toIntervalDay(3))))
    GROUP BY
        raw_sessions_v3.session_id_v7) AS e__session ON equals(e.`$session_id_uuid`, e__session.session_id_v7)
WHERE
    and(equals(e.team_id, <TEAM_ID>), and(greaterOrEquals(toTimeZone(e.timestamp, %(hogql_val_19)s), toStartOfDay(assumeNotNull(toDateTime(%(hogql_val_20)s, %(hogql_val_21)s)))), lessOrEquals(toTimeZone(e.timestamp, %(hogql_val_22)s), assumeNotNull(toDateTime(%(hogql_val_23)s, %(hogql_val_24)s))), equals(e.event, %(hogql_val_25)s), in(if(not(empty(e__override.distinct_id)), e__override.person_id, e.person_id), (SELECT
                    cohortpeople.person_id AS person_id
                FROM
                    cohortpeople
                WHERE
                    and(equals(cohortpeople.team_id, <TEAM_ID>), and(equals(cohortpeople.cohort_id, 2), equals(cohortpeople.version, 0)))))))
GROUP BY
    day_start,
    breakdown_value
LIMIT 50000\
"""
        )

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
        assert self.generalize_sql(actual) == snapshot(
            """\
SELECT
    s.session_id AS session_id,
    min(toTimeZone(s.min_first_timestamp, %(hogql_val_3)s)) AS start_time
FROM
    session_replay_events AS s
    LEFT JOIN (SELECT
        path(argMinMerge(raw_sessions_v3.entry_url)) AS `$entry_pathname`,
        raw_sessions_v3.session_id_v7 AS session_id_v7
    FROM
        raw_sessions_v3
    WHERE
        and(equals(raw_sessions_v3.team_id, <TEAM_ID>), greaterOrEquals(raw_sessions_v3.session_timestamp, minus(%(hogql_val_0)s, toIntervalDay(3))), lessOrEquals(raw_sessions_v3.session_timestamp, plus(now64(6, %(hogql_val_1)s), toIntervalDay(3))))
    GROUP BY
        raw_sessions_v3.session_id_v7) AS s__session ON equals(toUInt128(accurateCastOrNull(s.session_id, %(hogql_val_2)s)), s__session.session_id_v7)
WHERE
    and(equals(s.team_id, <TEAM_ID>), ifNull(equals(s__session.`$entry_pathname`, %(hogql_val_4)s), 0), greaterOrEquals(toTimeZone(s.min_first_timestamp, %(hogql_val_5)s), %(hogql_val_6)s), less(toTimeZone(s.min_first_timestamp, %(hogql_val_7)s), now64(6, %(hogql_val_8)s)))
GROUP BY
    s.session_id
LIMIT 50000\
"""
        )

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
        assert self.generalize_sql(actual) == snapshot(
            """\
SELECT
    sessions.session_id AS session_id,
    sessions.`$urls` AS `$urls`,
    sessions.`$start_timestamp` AS `$start_timestamp`
FROM
    (SELECT
        toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions_v3.session_id_v7, 64), bitShiftRight(raw_sessions_v3.session_id_v7, 64)))) AS session_id,
        arrayDistinct(arrayFlatten(groupArray(raw_sessions_v3.urls))) AS `$urls`,
        min(toTimeZone(raw_sessions_v3.min_timestamp, %(hogql_val_0)s)) AS `$start_timestamp`,
        raw_sessions_v3.session_id_v7 AS session_id_v7
    FROM
        raw_sessions_v3
    WHERE
        and(equals(raw_sessions_v3.team_id, <TEAM_ID>), greaterOrEquals(raw_sessions_v3.session_timestamp, minus(minus(now64(6, %(hogql_val_1)s), toIntervalDay(7)), toIntervalDay(3))))
    GROUP BY
        raw_sessions_v3.session_id_v7) AS sessions
WHERE
    ifNull(greaterOrEquals(sessions.`$start_timestamp`, minus(now64(6, %(hogql_val_2)s), toIntervalDay(7))), 0)
LIMIT 50000\
"""
        )

    def test_point_query(self):
        actual = self.print_query(
            """
    select
       session_id
    from sessions
    where session_id == '01995624-6a63-7cc4-800c-f5a45d99fa9b'
    """
        )
        assert self.generalize_sql(actual) == snapshot(
            """\
SELECT
    sessions.session_id AS session_id
FROM
    (SELECT
        toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions_v3.session_id_v7, 64), bitShiftRight(raw_sessions_v3.session_id_v7, 64)))) AS session_id,
        raw_sessions_v3.session_id_v7 AS session_id_v7
    FROM
        raw_sessions_v3
    WHERE
        and(equals(raw_sessions_v3.team_id, <TEAM_ID>), equals(raw_sessions_v3.session_timestamp, fromUnixTimestamp64Milli(toUInt64(bitShiftRight(toUInt128(accurateCastOrNull(%(hogql_val_0)s, %(hogql_val_1)s)), 80)))))
    GROUP BY
        raw_sessions_v3.session_id_v7) AS sessions
WHERE
    ifNull(equals(sessions.session_id, %(hogql_val_2)s), 0)
LIMIT 50000"""
        )
