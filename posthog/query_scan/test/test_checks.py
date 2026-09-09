from datetime import date, datetime

from freezegun import freeze_time
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import DateRange, HogQLFilters, HogQLQueryModifiers, PersonsArgMaxVersion

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import HogQLQueryExecutor

from posthog.query_scan.analyze import ScanThresholds, analyze
from posthog.query_scan.checks.event_filter import check_event_filter
from posthog.query_scan.checks.persons import check_persons_join
from posthog.query_scan.checks.start_date import check_start_date
from posthog.query_scan.explain import parse_query_plan
from posthog.query_scan.test.test_explain import MIXED_PRUNING_PLAN, load_plan

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

NOW = "2026-03-15T12:00:00Z"

_PERSONS_JOIN_SQL = "SELECT count() FROM events AS e JOIN persons AS p ON e.person_id = p.id WHERE e.event = 'purchase'"
_COHORT_FILTER_SQL = (
    "SELECT count() FROM events AS e JOIN persons AS p "
    "ON e.person_id = p.id AND p.id IN (SELECT person_id FROM cohort_people) "
    "WHERE e.event = 'purchase'"
)
_PERSONS_JOIN_WITHOUT_EVENTS_SQL = "SELECT count() FROM cohort_people AS cp JOIN persons AS p ON cp.person_id = p.id"


class QueryScanCheckTest(BaseTest):
    def prepare(
        self,
        sql: str,
        *,
        filters: HogQLFilters | None = None,
        modifiers: HogQLQueryModifiers | None = None,
    ) -> tuple[ast.AST, HogQLContext]:
        executor = HogQLQueryExecutor(
            query=parse_select(sql),
            team=self.team,
            query_type="HogQLQuery",
            filters=filters,
            modifiers=modifiers,
            limit_context=LimitContext.QUERY_ASYNC,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_prepared_ast is not None
        assert executor.clickhouse_context is not None
        return executor.clickhouse_prepared_ast, executor.clickhouse_context


class TestEventFilterCheck(QueryScanCheckTest):
    def setUp(self) -> None:
        super().setUp()
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="purchase_events",
            query={"query": "SELECT event AS event, timestamp AS timestamp FROM events WHERE event IN ('a', 'b')"},
            columns={"event": "String", "timestamp": "DateTime"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="every_event",
            query={"query": "SELECT event AS event, timestamp AS timestamp FROM events"},
            columns={"event": "String", "timestamp": "DateTime"},
        )

    @parameterized.expand(
        [
            ("equality", "SELECT count() FROM events WHERE event = 'purchase'", "usable", None),
            ("in a list", "SELECT count() FROM events WHERE event IN ('a', 'b')", "usable", None),
            (
                "or of event names only",
                "SELECT count() FROM events WHERE event = 'a' OR event = 'b'",
                "usable",
                None,
            ),
            (
                "inside an or with another condition",
                "SELECT count() FROM events WHERE properties.plan = 'pro' OR event = 'upgrade'",
                "not_used",
                "in_or",
            ),
            (
                "an or where no branch names the event",
                "SELECT count() FROM events WHERE (properties.plan = 'pro' AND properties.device = 'mobile') "
                "OR properties.browser = 'Chrome'",
                "none",
                None,
            ),
            (
                "an or with the event named in an and",
                "SELECT count() FROM events WHERE (event = 'a' AND properties.plan = 'pro') OR event = 'b'",
                "usable",
                None,
            ),
            (
                "wrapped in a function",
                "SELECT count() FROM events WHERE lower(event) = 'purchase'",
                "not_used",
                "wrapped",
            ),
            (
                "negated",
                "SELECT count() FROM events WHERE event NOT IN ('$pageview')",
                "not_used",
                "negated",
            ),
            (
                "a pattern with a fixed prefix",
                "SELECT count() FROM events WHERE event LIKE 'purchase%'",
                "usable",
                None,
            ),
            (
                "a case-insensitive pattern",
                "SELECT count() FROM events WHERE event ILIKE 'purchase%'",
                "not_used",
                "not_pruned",
            ),
            (
                "named in the ON of an inner join",
                "SELECT count() FROM events AS e INNER JOIN cohort_people AS cp "
                "ON e.person_id = cp.person_id AND e.event = 'purchase'",
                "usable",
                None,
            ),
            (
                "named in the ON of a left join, which keeps the rows that fail it",
                "SELECT count() FROM events AS e LEFT JOIN cohort_people AS cp "
                "ON e.person_id = cp.person_id AND e.event = 'purchase'",
                "none",
                None,
            ),
            (
                "compared to another column",
                "SELECT count() FROM events WHERE event = distinct_id",
                "not_used",
                "dynamic",
            ),
            ("no event condition at all", "SELECT count() FROM events", "none", None),
            (
                "filter inside a saved view",
                "SELECT count() FROM purchase_events WHERE timestamp > now() - interval 7 day",
                "usable",
                None,
            ),
            (
                "filter outside an unfiltered saved view",
                "SELECT count() FROM every_event WHERE event = 'a'",
                "usable",
                None,
            ),
            (
                "one branch of a union has no filter",
                "SELECT count() FROM events WHERE event = 'a' UNION ALL SELECT count() FROM events",
                "none",
                None,
            ),
            (
                "filter outside a subquery that limits its own rows",
                "SELECT count() FROM (SELECT event FROM events LIMIT 1000000) WHERE event = 'a'",
                "none",
                None,
            ),
            (
                "filter outside a union of two events reads",
                "SELECT count() FROM (SELECT event FROM events UNION ALL SELECT event FROM events) WHERE event = 'a'",
                "usable",
                None,
            ),
            (
                # Positional aliases rename by the table's column order, so `kind` is `event`.
                "filter on a renamed event column",
                "SELECT count() FROM events AS e (id, kind, props, ts) WHERE e.kind = 'a'",
                "usable",
                None,
            ),
        ]
    )
    @freeze_time(NOW)
    def test_classification(self, _name: str, sql: str, expected_class: str, expected_reason: str | None) -> None:
        tree, _context = self.prepare(sql)

        outcome = check_event_filter(tree)

        self.assertEqual(outcome.classification, expected_class)
        self.assertEqual(outcome.reason, expected_reason)

    @parameterized.expand(
        [
            ("clickhouse used the key", "event_filter_usable", "usable", None),
            ("clickhouse dropped the key", "no_event_filter", "not_used", "not_pruned"),
        ]
    )
    @freeze_time(NOW)
    def test_the_plan_overrules_the_tree(
        self, _name: str, fixture: str, expected_class: str, expected_reason: str | None
    ) -> None:
        tree, _context = self.prepare("SELECT count() FROM events WHERE event = 'purchase'")

        outcome = check_event_filter(tree, parse_query_plan(load_plan(fixture)))

        self.assertEqual(outcome.classification, expected_class)
        self.assertEqual(outcome.reason, expected_reason)

    @parameterized.expand(
        [
            (
                "the pruning read first",
                "SELECT count() FROM events WHERE event = 'purchase' "
                "UNION ALL SELECT count() FROM events WHERE match(event, 'x')",
            ),
            (
                "the wrapped read first",
                "SELECT count() FROM events WHERE match(event, 'x') "
                "UNION ALL SELECT count() FROM events WHERE event = 'purchase'",
            ),
        ]
    )
    @freeze_time(NOW)
    def test_a_plan_where_one_read_pruned_keeps_the_reason_the_tree_found(self, _name: str, sql: str) -> None:
        tree, _context = self.prepare(sql)

        outcome = check_event_filter(tree, MIXED_PRUNING_PLAN)

        self.assertEqual(outcome.classification, "not_used")
        self.assertEqual(outcome.reason, "wrapped")
        clause = outcome.clause
        assert isinstance(clause, ast.Call)
        self.assertEqual(clause.name, "match")

    @freeze_time(NOW)
    def test_a_plan_that_contradicts_several_usable_filters_names_no_clause(self) -> None:
        tree, _context = self.prepare(
            "SELECT count() FROM events WHERE event = 'a' UNION ALL SELECT count() FROM events WHERE event = 'b'"
        )

        outcome = check_event_filter(tree, MIXED_PRUNING_PLAN)

        self.assertEqual(outcome.classification, "not_used")
        self.assertEqual(outcome.reason, "not_pruned")
        self.assertIsNone(outcome.clause)


class TestStartDateCheck(QueryScanCheckTest):
    @parameterized.expand(
        [
            (
                "relative interval",
                "SELECT count() FROM events WHERE timestamp > now() - interval 30 day",
                "bound",
                date(2026, 2, 13),
            ),
            (
                "explicit date string",
                "SELECT count() FROM events WHERE timestamp >= '2026-01-01'",
                "bound",
                date(2026, 1, 1),
            ),
            (
                "toDateTime constant",
                "SELECT count() FROM events WHERE timestamp > toDateTime('2026-01-05 08:00:00')",
                "bound",
                date(2026, 1, 5),
            ),
            (
                "start of day",
                "SELECT count() FROM events WHERE timestamp >= toStartOfDay(now())",
                "bound",
                date(2026, 3, 15),
            ),
            (
                "today minus an interval",
                "SELECT count() FROM events WHERE timestamp > today() - interval 7 day",
                "bound",
                date(2026, 3, 8),
            ),
            (
                "the column on the right",
                "SELECT count() FROM events WHERE now() - interval 10 day < timestamp",
                "bound",
                date(2026, 3, 5),
            ),
            (
                "wrapped in toDate",
                "SELECT count() FROM events WHERE toDate(timestamp) >= '2026-02-01'",
                "bound",
                date(2026, 2, 1),
            ),
            (
                "between",
                "SELECT count() FROM events WHERE timestamp BETWEEN '2026-02-01' AND '2026-02-10'",
                "bound",
                date(2026, 2, 1),
            ),
            (
                "a constant date function",
                "SELECT count() FROM events WHERE timestamp >= toDate('2026-01-01')",
                "bound",
                date(2026, 1, 1),
            ),
            (
                "the shorthand for an interval",
                "SELECT count() FROM events WHERE timestamp >= subtractDays(now(), 7)",
                "bound",
                date(2026, 3, 8),
            ),
            (
                "the shorthand for a month interval",
                "SELECT count() FROM events WHERE timestamp >= subtractMonths(now(), 2)",
                "bound",
                date(2026, 1, 15),
            ),
            (
                "a fixed expression the evaluator does not cover",
                "SELECT count() FROM events WHERE timestamp >= fromUnixTimestamp(1767225600)",
                "bound",
                None,
            ),
            (
                "an interval too large to hold",
                "SELECT count() FROM events WHERE timestamp >= now() - interval 1000000000 day",
                "bound",
                None,
            ),
            (
                "a shift that runs off the start of time",
                "SELECT count() FROM events WHERE timestamp >= toDateTime('0001-01-02') - interval 100 year",
                "bound",
                None,
            ),
            (
                "compared to another column",
                "SELECT count() FROM events WHERE timestamp > toDateTime(properties.signup_time)",
                "column",
                None,
            ),
            ("no bound at all", "SELECT count() FROM events", "none", None),
            (
                "bound only inside an or",
                "SELECT count() FROM events WHERE timestamp > now() - interval 1 day OR event = 'a'",
                "none",
                None,
            ),
            (
                "bound outside a subquery that limits its own rows",
                "SELECT count() FROM (SELECT timestamp FROM events ORDER BY timestamp LIMIT 1000000) "
                "WHERE timestamp >= '2026-01-01'",
                "none",
                None,
            ),
            (
                "bound outside a union of two events reads",
                "SELECT count() FROM (SELECT timestamp FROM events UNION ALL SELECT timestamp FROM events) "
                "WHERE timestamp >= '2026-01-01'",
                "bound",
                date(2026, 1, 1),
            ),
            (
                # Positional aliases rename by the table's column order, so `ts` is `timestamp`.
                "bound on a renamed timestamp column",
                "SELECT count() FROM events AS e (id, kind, props, ts) WHERE e.ts >= '2026-01-01'",
                "bound",
                date(2026, 1, 1),
            ),
        ]
    )
    @freeze_time(NOW)
    def test_lower_bound(self, _name: str, sql: str, expected_class: str, expected_date_from: date | None) -> None:
        tree, _context = self.prepare(sql)

        outcome = check_start_date(tree)

        self.assertEqual(outcome.classification, expected_class)
        self.assertEqual(outcome.date_from, expected_date_from)

    @freeze_time(NOW)
    def test_upper_bound_defaults_to_today(self) -> None:
        tree, _context = self.prepare("SELECT count() FROM events WHERE timestamp > '2026-01-01'")

        outcome = check_start_date(tree)

        self.assertEqual(outcome.date_to, date(2026, 3, 15))
        self.assertIsNone(outcome.upper)

    @freeze_time(NOW)
    def test_upper_bound_is_read_from_the_query(self) -> None:
        tree, _context = self.prepare(
            "SELECT count() FROM events WHERE timestamp > '2026-01-01 08:30:00' AND timestamp < '2026-02-01 09:15:00'"
        )

        outcome = check_start_date(tree)

        self.assertEqual(outcome.date_to, date(2026, 2, 1))
        # The job counts with the exact instants where it has them, and rounds out to days otherwise.
        self.assertEqual(outcome.lower, datetime(2026, 1, 1, 8, 30))
        self.assertEqual(outcome.upper, datetime(2026, 2, 1, 9, 15))

    @parameterized.expand(
        [
            (
                "a whole month",
                "SELECT count() FROM events WHERE toStartOfMonth(timestamp) = '2026-03-01'",
                date(2026, 3, 1),
                date(2026, 4, 1),
            ),
            (
                "a whole day",
                "SELECT count() FROM events WHERE toDate(timestamp) = '2026-02-10'",
                date(2026, 2, 10),
                date(2026, 2, 11),
            ),
            (
                # 2026-02-01 is a Sunday, so both week modes end the week it starts on 2026-02-08.
                "every week up to one",
                "SELECT count() FROM events WHERE timestamp > '2026-01-01' AND toStartOfWeek(timestamp) <= '2026-02-01'",
                date(2026, 1, 1),
                date(2026, 2, 8),
            ),
            (
                # 2026-02-02 is a Monday, so the Monday week mode admits a day the Sunday mode does not.
                "every week up to one, with the modes disagreeing",
                "SELECT count() FROM events WHERE timestamp > '2026-01-01' AND toStartOfWeek(timestamp) <= '2026-02-02'",
                date(2026, 1, 1),
                date(2026, 2, 9),
            ),
            (
                "two truncations leave the upper bound unknown",
                "SELECT count() FROM events WHERE timestamp > '2026-01-01' "
                "AND toStartOfMonth(toStartOfWeek(timestamp)) <= '2026-02-01'",
                date(2026, 1, 1),
                date(2026, 3, 15),
            ),
        ]
    )
    @freeze_time(NOW)
    def test_a_truncated_bound_covers_the_interval_it_admits(
        self, _name: str, sql: str, expected_date_from: date, expected_date_to: date
    ) -> None:
        tree, _context = self.prepare(sql)

        outcome = check_start_date(tree)

        self.assertEqual(outcome.classification, "bound")
        self.assertEqual(outcome.date_from, expected_date_from)
        self.assertEqual(outcome.date_to, expected_date_to)

    @freeze_time(NOW)
    def test_two_events_reads_widen_the_range_to_cover_both(self) -> None:
        tree, _context = self.prepare(
            "SELECT count() FROM events WHERE timestamp > '2026-02-01' "
            "UNION ALL SELECT count() FROM events WHERE timestamp > '2026-01-01'"
        )

        outcome = check_start_date(tree)

        self.assertEqual(outcome.classification, "bound")
        self.assertEqual(outcome.date_from, date(2026, 1, 1))

    @freeze_time(NOW)
    def test_filters_placeholder_supplies_the_bound(self) -> None:
        tree, _context = self.prepare(
            "SELECT count() FROM events WHERE {filters}",
            filters=HogQLFilters(dateRange=DateRange(date_from="-7d")),
        )

        outcome = check_start_date(tree, has_filters_placeholder=True)

        self.assertEqual(outcome.classification, "bound")
        self.assertEqual(outcome.date_from, date(2026, 3, 8))

    @freeze_time(NOW)
    def test_a_read_the_placeholder_does_not_reach_does_not_blame_the_insight(self) -> None:
        tree, _context = self.prepare(
            "SELECT count() FROM events WHERE {filters} UNION ALL SELECT count() FROM events",
            filters=HogQLFilters(dateRange=DateRange(date_from="-7d")),
        )

        outcome = check_start_date(tree, has_filters_placeholder=True)

        self.assertEqual(outcome.classification, "none")
        self.assertIsNone(outcome.reason)

    @freeze_time(NOW)
    def test_filters_placeholder_with_no_date_range_blames_the_insight(self) -> None:
        tree, _context = self.prepare("SELECT count() FROM events WHERE {filters}")

        outcome = check_start_date(tree, has_filters_placeholder=True)

        self.assertEqual(outcome.classification, "none")
        self.assertEqual(outcome.reason, "filters")


class TestPersonsJoinCheck(QueryScanCheckTest):
    @parameterized.expand(
        [
            ("a join with nothing pushed in", _PERSONS_JOIN_SQL, None, True, True),
            (
                "a join with a cohort filter pushed in, argmax v1",
                _COHORT_FILTER_SQL,
                HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.V1),
                True,
                False,
            ),
            (
                "a join with a cohort filter pushed in, argmax v2",
                _COHORT_FILTER_SQL,
                HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.V2),
                True,
                False,
            ),
            (
                "a join whose person filter the planner could not push in",
                "SELECT count() FROM events AS e JOIN persons AS p ON e.person_id = p.id "
                "WHERE e.event = 'purchase' AND p.properties.email = 'someone@example.com'",
                HogQLQueryModifiers(optimizeJoinedFilters=True),
                True,
                True,
            ),
            ("a join from a table that is not events", _PERSONS_JOIN_WITHOUT_EVENTS_SQL, None, True, True),
            ("a read straight from the persons table", "SELECT count() FROM persons", None, False, False),
            (
                "a filtered read straight from the persons table",
                "SELECT count() FROM persons WHERE properties.email = 'someone@example.com'",
                None,
                False,
                False,
            ),
            (
                "a query that does not touch persons",
                "SELECT count() FROM events WHERE event = 'purchase'",
                None,
                False,
                False,
            ),
        ]
    )
    @freeze_time(NOW)
    def test_how_the_query_reached_the_persons_subquery(
        self,
        _name: str,
        sql: str,
        modifiers: HogQLQueryModifiers | None,
        expected_reads_persons: bool,
        expected_unfiltered: bool,
    ) -> None:
        _tree, context = self.prepare(sql, modifiers=modifiers)

        outcome = check_persons_join(context)

        self.assertEqual(outcome.reads_persons, expected_reads_persons)
        self.assertEqual(outcome.unfiltered, expected_unfiltered)

    @freeze_time(NOW)
    def test_a_reused_context_does_not_carry_the_previous_persons_join(self) -> None:
        shared = HogQLContext(team_id=self.team.pk)
        self._compile(_PERSONS_JOIN_SQL, shared)

        context = self._compile("SELECT count() FROM events WHERE event = 'purchase'", shared)

        self.assertFalse(check_persons_join(context).reads_persons)

    def _compile(self, sql: str, context: HogQLContext) -> HogQLContext:
        executor = HogQLQueryExecutor(
            query=parse_select(sql),
            team=self.team,
            query_type="HogQLQuery",
            limit_context=LimitContext.QUERY_ASYNC,
            context=context,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_context is not None
        return executor.clickhouse_context


class TestAnalyze(QueryScanCheckTest):
    @freeze_time(NOW)
    def test_an_unfiltered_scan_reports_both_findings_with_the_offending_clause(self) -> None:
        sql = "SELECT count() FROM events WHERE properties.plan = 'pro' OR event = 'upgrade'"
        tree, context = self.prepare(sql)

        result = analyze(
            tree,
            context,
            plan=None,
            rows_read=8_400_000_000,
            duration_ms=19_000,
            events_in_range=8_400_000_000,
            person_rows=None,
            has_filters_placeholder=False,
            thresholds=ScanThresholds(),
            source=sql,
        )

        self.assertEqual(result.finding_kinds(), ["event_filter_not_used", "no_start_date"])
        self.assertEqual(result.event_filter_class, "not_used")
        self.assertEqual(result.event_filter_reason, "in_or")
        self.assertEqual(result.start_date_class, "none")
        self.assertEqual(result.findings[0].clause, "properties.plan = 'pro' OR event = 'upgrade'")

    @freeze_time(NOW)
    def test_a_clause_is_quoted_only_from_the_query_the_person_typed(self) -> None:
        tree, context = self.prepare("SELECT count() FROM events WHERE properties.plan = 'pro' OR event = 'upgrade'")

        # The SQL of an inlined saved view carries the view's offsets, not the typed query's.
        result = analyze(
            tree,
            context,
            plan=None,
            rows_read=8_400_000_000,
            duration_ms=19_000,
            events_in_range=8_400_000_000,
            person_rows=None,
            has_filters_placeholder=False,
            thresholds=ScanThresholds(),
            source="SELECT count() FROM my_view",
        )

        self.assertEqual(result.finding_kinds(), ["event_filter_not_used", "no_start_date"])
        self.assertIsNone(result.findings[0].clause)

    @freeze_time(NOW)
    def test_a_filtered_and_bounded_query_stays_quiet(self) -> None:
        tree, context = self.prepare(
            "SELECT count() FROM events WHERE event = 'purchase' AND timestamp > now() - interval 30 day"
        )

        result = analyze(
            tree,
            context,
            plan=parse_query_plan(load_plan("event_filter_usable")),
            rows_read=3_000_000,
            duration_ms=2000,
            events_in_range=3_000_000_000,
            person_rows=None,
            has_filters_placeholder=False,
            thresholds=ScanThresholds(),
        )

        self.assertEqual(result.findings, [])
        self.assertEqual(result.event_filter_class, "usable")
        self.assertEqual(result.start_date_class, "bound")
        assert result.range is not None
        self.assertEqual(result.range.date_from, date(2026, 2, 13))

    @freeze_time(NOW)
    def test_a_persons_join_over_the_ratio_reports_the_join(self) -> None:
        tree, context = self.prepare(
            "SELECT count() FROM events AS e JOIN persons AS p ON e.person_id = p.id "
            "WHERE e.event = 'purchase' AND e.timestamp > now() - interval 30 day"
        )

        result = analyze(
            tree,
            context,
            plan=None,
            rows_read=3_000_000,
            duration_ms=3000,
            events_in_range=3_000_000_000,
            person_rows=150_000_000,
            has_filters_placeholder=False,
            thresholds=ScanThresholds(),
        )

        self.assertEqual(result.finding_kinds(), ["persons_join"])

    @freeze_time(NOW)
    def test_the_event_gate_leaves_out_what_the_persons_join_read(self) -> None:
        tree, context = self.prepare(
            "SELECT count() FROM events AS e JOIN persons AS p ON e.person_id = p.id "
            "WHERE e.timestamp > now() - interval 30 day"
        )

        result = analyze(
            tree,
            context,
            plan=None,
            rows_read=151_000_000,
            duration_ms=9000,
            events_in_range=100_000_000,
            person_rows=150_000_000,
            has_filters_placeholder=False,
            thresholds=ScanThresholds(),
        )

        self.assertEqual(result.finding_kinds(), ["persons_join"])
        self.assertEqual(result.event_filter_class, "none")
        assert result.event_ratio is not None
        self.assertAlmostEqual(result.event_ratio, 0.01)

    @freeze_time(NOW)
    def test_a_persons_join_with_no_events_read_is_not_reported(self) -> None:
        tree, context = self.prepare(_PERSONS_JOIN_WITHOUT_EVENTS_SQL)

        result = analyze(
            tree,
            context,
            plan=None,
            rows_read=3_000_000,
            duration_ms=3000,
            events_in_range=None,
            person_rows=150_000_000,
            has_filters_placeholder=False,
            thresholds=ScanThresholds(),
        )

        self.assertEqual(result.finding_kinds(), [])
