from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import HogQLQueryExecutor

from posthog.query_scan.tree_facts import TreeFacts, tree_facts

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

_RECENT = "timestamp >= now() - interval 7 day"


class TestTreeFacts(BaseTest):
    def test_repeated_cte_presentation_branches(self) -> None:
        tree = self.prepare("""
            WITH totals AS (
                SELECT distinct_id, count() AS n FROM events
                WHERE event = 'lesson_completed' AND timestamp >= now() - interval 7 day
                GROUP BY distinct_id
            )
            SELECT 'people' AS label, count() AS value FROM totals
            UNION ALL
            SELECT 'lessons' AS label, sum(n) AS value FROM totals
        """)
        facts = tree_facts(tree)
        assert facts is not None
        self.assertEqual(facts.repeated_cte_branches, 2)

    @parameterized.expand(
        [
            ("aliased", "SELECT count() FROM totals AS a UNION ALL SELECT sum(n) FROM totals AS b", 2),
            (
                "three branches",
                "SELECT count() FROM totals UNION ALL SELECT sum(n) FROM totals UNION ALL SELECT max(n) FROM totals",
                3,
            ),
            ("filtered branch", "SELECT count() FROM totals UNION ALL SELECT sum(n) FROM totals WHERE n > 1", 0),
            ("single reference", "SELECT count() FROM totals", 0),
            (
                "presentation wrapper",
                "SELECT * FROM (SELECT count() AS n FROM totals UNION ALL SELECT sum(n) AS n FROM totals) ORDER BY n",
                2,
            ),
            ("union distinct", "SELECT count() FROM totals UNION DISTINCT SELECT sum(n) FROM totals", 0),
            ("different source", "SELECT count() FROM totals UNION ALL SELECT count() FROM events", 0),
            ("unused cte", "SELECT count() FROM events UNION ALL SELECT count() FROM events", 0),
            ("grouped branch", "SELECT count() FROM totals GROUP BY n UNION ALL SELECT sum(n) FROM totals", 0),
            (
                "shadowed name",
                "SELECT count() FROM totals UNION ALL (WITH totals AS (SELECT 1 AS n) SELECT sum(n) FROM totals)",
                0,
            ),
            ("explicit limit", "(SELECT count() FROM totals LIMIT 1) UNION ALL SELECT sum(n) FROM totals", 0),
        ]
    )
    def test_repeated_cte_scope_and_branch_shape(self, _name: str, branches: str, expected: int) -> None:
        tree = self.prepare(
            "WITH totals AS (SELECT distinct_id, count() AS n FROM events GROUP BY distinct_id) " + branches
        )
        facts = tree_facts(tree)
        assert facts is not None
        self.assertEqual(facts.repeated_cte_branches, expected)

    def test_repeated_cte_through_another_cte(self) -> None:
        tree = self.prepare("""
            WITH counts AS (SELECT distinct_id, count() AS n FROM events GROUP BY distinct_id),
                 totals AS (SELECT * FROM counts)
            SELECT count() FROM totals UNION ALL SELECT sum(n) FROM totals
        """)
        facts = tree_facts(tree)
        assert facts is not None
        self.assertEqual(facts.repeated_cte_branches, 2)

    def test_repeated_constant_cte_beside_unused_events(self) -> None:
        tree = self.prepare("""
            WITH unused AS (SELECT count() FROM events), totals AS (SELECT 1 AS n)
            SELECT count() FROM totals UNION ALL SELECT sum(n) FROM totals
        """)
        facts = tree_facts(tree)
        self.assertEqual(facts.repeated_cte_branches if facts else 0, 0)

    def test_repeated_cte_is_scoped_to_the_selected_reads(self) -> None:
        from posthog.query_scan.tree import find_events_reads

        tree = self.prepare("""
            WITH totals AS (SELECT count() AS n FROM events)
            SELECT sum(n) FROM totals UNION ALL SELECT max(n) FROM totals
        """)
        self.assertIsNone(tree_facts(tree, reads=[]))
        reads = find_events_reads(tree)
        facts = tree_facts(tree, reads=reads)
        assert facts is not None
        self.assertEqual(TreeFacts.from_payload(facts.to_payload()), facts)

    def test_repeated_cte_inside_a_view_is_not_reported_on_the_outer_query(self) -> None:
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v_counts",
            query={
                "kind": "HogQLQuery",
                "query": "WITH totals AS (SELECT count() AS n FROM events) SELECT sum(n) AS n FROM totals UNION ALL SELECT max(n) AS n FROM totals",
            },
            columns={"n": "UInt64"},
        )
        facts = tree_facts(self.prepare("SELECT * FROM v_counts"))
        assert facts is not None
        self.assertEqual(facts.repeated_cte_branches, 0)

    def prepare(self, sql: str) -> ast.AST:
        executor = HogQLQueryExecutor(
            query=parse_select(sql),
            team=self.team,
            query_type="HogQLQuery",
            limit_context=LimitContext.QUERY_ASYNC,
        )
        executor.generate_clickhouse_sql()
        assert executor.clickhouse_prepared_ast is not None
        return executor.clickhouse_prepared_ast

    @parameterized.expand(
        [
            (
                "a relative bound",
                f"SELECT count() FROM events WHERE event = 'a' AND {_RECENT}",
                TreeFacts(timestamp_bound=True),
            ),
            (
                "a bound on another column",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp > toDateTime(properties.signup_time)",
                TreeFacts(timestamp_bound=True),
            ),
            (
                "a start from a subquery",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp >= (SELECT now() - interval 7 day)",
                TreeFacts(timestamp_bound=True, start_date_hidden_from_plan=True),
            ),
            (
                "an end from a subquery is not a start",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp < (SELECT now())",
                TreeFacts(),
            ),
            (
                "a bound on the wrapped timestamp",
                "SELECT count() FROM events WHERE event = 'a' AND toDate(timestamp) >= today() - 7",
                TreeFacts(timestamp_bound=True),
            ),
            (
                "a bound with the timestamp on the right",
                "SELECT count() FROM events WHERE event = 'a' AND now() - interval 7 day <= timestamp",
                TreeFacts(timestamp_bound=True),
            ),
            ("an end date only", "SELECT count() FROM events WHERE event = 'a' AND timestamp < now()", TreeFacts()),
            (
                "a bound inside an OR",
                f"SELECT count() FROM events WHERE event = 'a' AND ({_RECENT} OR properties.plan = 'pro')",
                TreeFacts(),
            ),
            (
                "two reads, one unbounded",
                f"SELECT count() FROM events AS e JOIN (SELECT distinct_id FROM events WHERE event = 'b') AS s "
                f"ON e.distinct_id = s.distinct_id WHERE e.event = 'a' AND e.{_RECENT}",
                TreeFacts(),
            ),
            (
                "a property standing in for an event",
                f"SELECT count() FROM events WHERE properties.$current_url = 'https://example.com/x' AND {_RECENT}",
                TreeFacts(timestamp_bound=True, property_filter=True),
            ),
            (
                "a property beside an event condition",
                f"SELECT count() FROM events WHERE event = 'a' AND properties.plan = 'pro' AND {_RECENT}",
                TreeFacts(timestamp_bound=True),
            ),
            (
                "a property inside an OR with the event",
                f"SELECT count() FROM events WHERE (event = 'a' OR properties.plan = 'pro') AND {_RECENT}",
                TreeFacts(timestamp_bound=True),
            ),
            (
                "each person's first event",
                "SELECT person_id, min(timestamp) FROM events GROUP BY person_id",
                TreeFacts(all_history=True),
            ),
            (
                "the value at each person's first event",
                "SELECT person_id, argMin(properties.plan, timestamp) FROM events GROUP BY person_id",
                TreeFacts(all_history=True),
            ),
            (
                "a first-event window",
                "SELECT person_id, row_number() OVER (PARTITION BY person_id ORDER BY timestamp ASC) AS n FROM events",
                TreeFacts(all_history=True),
            ),
            (
                "a first-event helper beside an unbounded main read",
                "SELECT count() FROM events AS e JOIN (SELECT person_id, min(timestamp) AS first FROM events "
                "GROUP BY person_id) AS f ON e.person_id = f.person_id WHERE e.event = 'a'",
                TreeFacts(),
            ),
            (
                "each person's first event in a range",
                f"SELECT person_id, min(timestamp) FROM events WHERE {_RECENT} GROUP BY person_id",
                TreeFacts(timestamp_bound=True),
            ),
            ("grouping by event", "SELECT event, count() FROM events GROUP BY event", TreeFacts(groups_by_event=True)),
            (
                "grouping by event position",
                "SELECT event, count() FROM events GROUP BY 1",
                TreeFacts(groups_by_event=True),
            ),
            (
                "grouping by event with an event condition",
                "SELECT event, count() FROM events WHERE event IN ('a', 'b') GROUP BY event",
                TreeFacts(),
            ),
            (
                "distinct people over any event",
                f"SELECT count(DISTINCT person_id) FROM events WHERE {_RECENT}",
                TreeFacts(timestamp_bound=True, counts_any_event=True),
            ),
            (
                "unique sessions over any event",
                f"SELECT uniq($session_id) FROM events WHERE {_RECENT}",
                TreeFacts(timestamp_bound=True, counts_any_event=True),
            ),
            (
                "distinct people over one event",
                f"SELECT count(DISTINCT person_id) FROM events WHERE event = 'a' AND {_RECENT}",
                TreeFacts(timestamp_bound=True),
            ),
            (
                "each person's last event",
                "SELECT person_id, max(timestamp) FROM events GROUP BY person_id",
                TreeFacts(counts_any_event=True),
            ),
            (
                "a last-event window",
                "SELECT person_id, row_number() OVER (PARTITION BY person_id ORDER BY timestamp DESC) AS n FROM events",
                TreeFacts(counts_any_event=True),
            ),
            ("the last event", "SELECT max(timestamp) FROM events", TreeFacts()),
            ("a plain count", f"SELECT count() FROM events WHERE {_RECENT}", TreeFacts(timestamp_bound=True)),
        ]
    )
    def test_reads_the_facts_off_the_tree(self, _name: str, sql: str, expected: TreeFacts) -> None:
        self.assertEqual(tree_facts(self.prepare(sql)), expected)

    def test_a_query_without_events_has_no_facts(self) -> None:
        self.assertIsNone(tree_facts(self.prepare("SELECT 1")))

    def test_a_read_inside_a_saved_view_names_the_view(self) -> None:
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v_active",
            query={"kind": "HogQLQuery", "query": "SELECT event, timestamp, person_id FROM events WHERE event = 'a'"},
            columns={"event": "String", "timestamp": "DateTime64(6, 'UTC')", "person_id": "UUID"},
        )

        facts = tree_facts(self.prepare("SELECT count() FROM v_active"))

        assert facts is not None
        self.assertEqual(facts.view_name, "v_active")
        repeated = tree_facts(
            self.prepare(
                "WITH totals AS (SELECT count() AS n FROM v_active) SELECT sum(n) FROM totals UNION ALL SELECT max(n) FROM totals"
            )
        )
        assert repeated is not None
        self.assertEqual(repeated.view_name, "v_active")
        self.assertEqual(repeated.repeated_cte_branches, 2)
        mixed = tree_facts(
            self.prepare(
                "SELECT count() FROM events AS e JOIN v_active AS v ON e.person_id = v.person_id WHERE e.event = 'b'"
            )
        )
        assert mixed is not None
        self.assertIsNone(mixed.view_name)
