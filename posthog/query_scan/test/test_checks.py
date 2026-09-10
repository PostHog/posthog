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

from posthog.query_scan.analyze import QueryScanResult, ScanThresholds, analyze
from posthog.query_scan.checks.event_filter import check_event_filter
from posthog.query_scan.checks.persons import check_persons_join
from posthog.query_scan.checks.start_date import check_start_date
from posthog.query_scan.explain import QueryPlan, parse_query_plan
from posthog.query_scan.test.test_explain import MIXED_PRUNING_PLAN, load_plan

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

NOW = "2026-03-15T12:00:00Z"

_USABLE_PLAN = parse_query_plan(load_plan("event_filter_usable"))
_UNPRUNED_PLAN = parse_query_plan(load_plan("no_event_filter"))

_IN_OR_SQL = "SELECT count() FROM events WHERE properties.plan = 'pro' OR event = 'upgrade'"
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
            name="every_event",
            query={"query": "SELECT event AS event, timestamp AS timestamp FROM events"},
            columns={"event": "String", "timestamp": "DateTime"},
        )

    @parameterized.expand(
        [
            ("equality", "SELECT count() FROM events WHERE event = 'purchase'", "usable", None),
            (
                "or of event names only",
                "SELECT count() FROM events WHERE event = 'a' OR event = 'b'",
                "usable",
                None,
            ),
            (
                "an or with the event named in an and",
                "SELECT count() FROM events WHERE (event = 'a' AND properties.plan = 'pro') OR event = 'b'",
                "usable",
                None,
            ),
            (
                "inside an or with another condition",
                _IN_OR_SQL,
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
                "compared to another column",
                "SELECT count() FROM events WHERE event = distinct_id",
                "not_used",
                "dynamic",
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
                "a regular expression",
                "SELECT count() FROM events WHERE event =~ 'purchase'",
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
            ("no event condition at all", "SELECT count() FROM events", "none", None),
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
            (
                "the plan used the key",
                "SELECT count() FROM events WHERE event = 'purchase'",
                _USABLE_PLAN,
                "usable",
                None,
                False,
            ),
            (
                "the plan dropped the key",
                "SELECT count() FROM events WHERE event = 'purchase'",
                _UNPRUNED_PLAN,
                "not_used",
                "not_pruned",
                True,
            ),
            (
                "the plan dropped the key on one of several usable reads",
                "SELECT count() FROM events WHERE event = 'a' UNION ALL SELECT count() FROM events WHERE event = 'b'",
                MIXED_PRUNING_PLAN,
                "not_used",
                "not_pruned",
                False,
            ),
            (
                "a read the tree already faulted keeps its own reason",
                "SELECT count() FROM events WHERE event = 'purchase' "
                "UNION ALL SELECT count() FROM events WHERE match(event, 'x')",
                MIXED_PRUNING_PLAN,
                "not_used",
                "wrapped",
                True,
            ),
            (
                "a negated filter is not excused by the key",
                "SELECT count() FROM events WHERE event != 'purchase'",
                _USABLE_PLAN,
                "not_used",
                "negated",
                True,
            ),
        ]
    )
    @freeze_time(NOW)
    def test_the_plan_overrules_the_tree(
        self,
        _name: str,
        sql: str,
        plan: QueryPlan,
        expected_class: str,
        expected_reason: str | None,
        expects_clause: bool,
    ) -> None:
        tree, _context = self.prepare(sql)

        outcome = check_event_filter(tree, plan)

        self.assertEqual(outcome.classification, expected_class)
        self.assertEqual(outcome.reason, expected_reason)
        self.assertEqual(outcome.clause is not None, expects_clause)


class TestStartDateCheck(QueryScanCheckTest):
    @parameterized.expand(
        [
            (
                "a relative interval",
                "SELECT count() FROM events WHERE timestamp > now() - interval 30 day",
                "bound",
                date(2026, 2, 13),
            ),
            (
                "a constant date function",
                "SELECT count() FROM events WHERE timestamp >= toDate('2026-01-01')",
                "bound",
                date(2026, 1, 1),
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
                "two events reads widen the range to the earlier bound",
                "SELECT count() FROM events WHERE timestamp > '2026-02-01' "
                "UNION ALL SELECT count() FROM events WHERE timestamp > '2026-01-01'",
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

    @parameterized.expand(
        [
            (
                "no upper bound at all",
                "SELECT count() FROM events WHERE timestamp > '2026-01-01'",
                datetime(2026, 1, 1),
                None,
                date(2026, 3, 15),
            ),
            (
                "a fixed upper bound",
                "SELECT count() FROM events WHERE timestamp > '2026-01-01 08:30:00' "
                "AND timestamp < '2026-02-01 09:15:00'",
                datetime(2026, 1, 1, 8, 30),
                datetime(2026, 2, 1, 9, 15),
                date(2026, 2, 1),
            ),
            (
                "a whole month",
                "SELECT count() FROM events WHERE toStartOfMonth(timestamp) = '2026-03-01'",
                datetime(2026, 3, 1),
                datetime(2026, 4, 1),
                date(2026, 4, 1),
            ),
            (
                # 2026-02-01 is a Sunday, so both week modes end the week it starts on 2026-02-08.
                "every week up to a Sunday",
                "SELECT count() FROM events WHERE timestamp > '2026-01-01' AND toStartOfWeek(timestamp) <= '2026-02-01'",
                datetime(2026, 1, 1),
                datetime(2026, 2, 8),
                date(2026, 2, 8),
            ),
            (
                # 2026-02-02 is a Monday, so the Monday week mode admits a day the Sunday mode does not.
                "every week up to a Monday",
                "SELECT count() FROM events WHERE timestamp > '2026-01-01' AND toStartOfWeek(timestamp) <= '2026-02-02'",
                datetime(2026, 1, 1),
                datetime(2026, 2, 9),
                date(2026, 2, 9),
            ),
            (
                "two truncations leave the upper bound unknown",
                "SELECT count() FROM events WHERE timestamp > '2026-01-01' "
                "AND toStartOfMonth(toStartOfWeek(timestamp)) <= '2026-02-01'",
                datetime(2026, 1, 1),
                None,
                date(2026, 3, 15),
            ),
        ]
    )
    @freeze_time(NOW)
    def test_upper_bound(
        self,
        _name: str,
        sql: str,
        expected_lower: datetime,
        expected_upper: datetime | None,
        expected_date_to: date,
    ) -> None:
        tree, _context = self.prepare(sql)

        outcome = check_start_date(tree)

        self.assertEqual(outcome.lower, expected_lower)
        self.assertEqual(outcome.upper, expected_upper)
        self.assertEqual(outcome.date_to, expected_date_to)

    @parameterized.expand(
        [
            (
                "a range is supplied",
                "SELECT count() FROM events WHERE {filters}",
                DateRange(date_from="-7d"),
                "bound",
                None,
            ),
            ("no range is supplied", "SELECT count() FROM events WHERE {filters}", None, "none", "filters"),
            (
                "a read the placeholder does not reach",
                "SELECT count() FROM events WHERE {filters} UNION ALL SELECT count() FROM events",
                DateRange(date_from="-7d"),
                "none",
                None,
            ),
        ]
    )
    @freeze_time(NOW)
    def test_the_filters_placeholder(
        self,
        _name: str,
        sql: str,
        date_range: DateRange | None,
        expected_class: str,
        expected_reason: str | None,
    ) -> None:
        filters = HogQLFilters(dateRange=date_range) if date_range is not None else None
        tree, _context = self.prepare(sql, filters=filters)

        outcome = check_start_date(tree, has_filters_placeholder=True)

        self.assertEqual(outcome.classification, expected_class)
        self.assertEqual(outcome.reason, expected_reason)


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
            ("a read straight from the persons table", "SELECT count() FROM persons", None, False, False),
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
    def scan(
        self,
        sql: str,
        *,
        plan: QueryPlan | None = None,
        rows_read: int,
        events_in_range: int | None = None,
        person_rows: int | None = None,
        source: str | None = None,
    ) -> QueryScanResult:
        tree, context = self.prepare(sql)
        return analyze(
            tree,
            context,
            plan=plan,
            rows_read=rows_read,
            duration_ms=19_000,
            events_in_range=events_in_range,
            person_rows=person_rows,
            has_filters_placeholder=False,
            thresholds=ScanThresholds(),
            source=source,
        )

    @parameterized.expand(
        [
            ("the query the person typed", _IN_OR_SQL, "properties.plan = 'pro' OR event = 'upgrade'"),
            # The SQL of an inlined saved view carries the view's offsets, not the typed query's.
            ("a query whose offsets are someone else's", "SELECT count() FROM my_view", None),
        ]
    )
    @freeze_time(NOW)
    def test_a_clause_is_quoted_only_from_the_query_the_person_typed(
        self, _name: str, source: str, expected_clause: str | None
    ) -> None:
        result = self.scan(_IN_OR_SQL, rows_read=8_400_000_000, events_in_range=8_400_000_000, source=source)

        self.assertEqual(result.finding_kinds(), ["event_filter_not_used", "no_start_date"])
        self.assertEqual(result.event_filter_reason, "in_or")
        self.assertEqual(result.start_date_class, "none")
        self.assertEqual(result.findings[0].clause, expected_clause)

    @freeze_time(NOW)
    def test_a_filtered_and_bounded_query_stays_quiet(self) -> None:
        result = self.scan(
            "SELECT count() FROM events WHERE event = 'purchase' AND timestamp > now() - interval 30 day",
            plan=_USABLE_PLAN,
            rows_read=3_000_000,
            events_in_range=3_000_000_000,
        )

        self.assertEqual(result.findings, [])
        self.assertEqual(result.event_filter_class, "usable")
        self.assertEqual(result.start_date_class, "bound")
        assert result.range is not None
        self.assertEqual(result.range.date_from, date(2026, 2, 13))

    @parameterized.expand(
        [
            (
                "over the persons ratio",
                "SELECT count() FROM events AS e JOIN persons AS p ON e.person_id = p.id "
                "WHERE e.event = 'purchase' AND e.timestamp > now() - interval 30 day",
                3_000_000,
                3_000_000_000,
                ["persons_join"],
            ),
            (
                "the persons rows are left out of the event gate",
                "SELECT count() FROM events AS e JOIN persons AS p ON e.person_id = p.id "
                "WHERE e.timestamp > now() - interval 30 day",
                151_000_000,
                100_000_000,
                ["persons_join"],
            ),
            (
                "no events read to move the person properties to",
                _PERSONS_JOIN_WITHOUT_EVENTS_SQL,
                3_000_000,
                None,
                [],
            ),
        ]
    )
    @freeze_time(NOW)
    def test_which_findings_a_persons_join_produces(
        self,
        _name: str,
        sql: str,
        rows_read: int,
        events_in_range: int | None,
        expected_kinds: list[str],
    ) -> None:
        result = self.scan(sql, rows_read=rows_read, events_in_range=events_in_range, person_rows=150_000_000)

        self.assertEqual(result.finding_kinds(), expected_kinds)
