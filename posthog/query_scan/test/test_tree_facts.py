from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import HogQLQueryExecutor

from posthog.query_scan.tree_facts import TreeFacts, tree_facts

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

_RECENT = "timestamp >= now() - interval 7 day"


def _facts(**overrides: object) -> TreeFacts:
    values: dict[str, object] = {
        "timestamp_bound": False,
        "property_filter": False,
        "all_history": False,
        "groups_by_event": False,
        "counts_any_event": False,
        "view_name": None,
    }
    return TreeFacts(**{**values, **overrides})  # type: ignore[arg-type]


class TestTreeFacts(BaseTest):
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
                _facts(timestamp_bound=True),
            ),
            (
                "a bound on another column",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp > toDateTime(properties.signup_time)",
                _facts(timestamp_bound=True),
            ),
            (
                "a bound on the wrapped timestamp",
                "SELECT count() FROM events WHERE event = 'a' AND toDate(timestamp) >= today() - 7",
                _facts(timestamp_bound=True),
            ),
            (
                "a bound with the timestamp on the right",
                "SELECT count() FROM events WHERE event = 'a' AND now() - interval 7 day <= timestamp",
                _facts(timestamp_bound=True),
            ),
            ("an end date only", "SELECT count() FROM events WHERE event = 'a' AND timestamp < now()", _facts()),
            (
                "a bound inside an OR",
                f"SELECT count() FROM events WHERE event = 'a' AND ({_RECENT} OR properties.plan = 'pro')",
                _facts(),
            ),
            (
                "two reads, one unbounded",
                f"SELECT count() FROM events AS e JOIN (SELECT distinct_id FROM events WHERE event = 'b') AS s "
                f"ON e.distinct_id = s.distinct_id WHERE e.event = 'a' AND e.{_RECENT}",
                _facts(),
            ),
            (
                "a property standing in for an event",
                f"SELECT count() FROM events WHERE properties.$current_url = 'https://example.com/x' AND {_RECENT}",
                _facts(timestamp_bound=True, property_filter=True),
            ),
            (
                "a property beside an event condition",
                f"SELECT count() FROM events WHERE event = 'a' AND properties.plan = 'pro' AND {_RECENT}",
                _facts(timestamp_bound=True),
            ),
            (
                "a property inside an OR with the event",
                f"SELECT count() FROM events WHERE (event = 'a' OR properties.plan = 'pro') AND {_RECENT}",
                _facts(timestamp_bound=True),
            ),
            (
                "each person's first event",
                "SELECT person_id, min(timestamp) FROM events GROUP BY person_id",
                _facts(all_history=True),
            ),
            (
                "the value at each person's first event",
                "SELECT person_id, argMin(properties.plan, timestamp) FROM events GROUP BY person_id",
                _facts(all_history=True),
            ),
            (
                "a first-event window",
                "SELECT person_id, row_number() OVER (PARTITION BY person_id ORDER BY timestamp ASC) AS n FROM events",
                _facts(all_history=True),
            ),
            (
                "each person's first event in a range",
                f"SELECT person_id, min(timestamp) FROM events WHERE {_RECENT} GROUP BY person_id",
                _facts(timestamp_bound=True),
            ),
            ("grouping by event", "SELECT event, count() FROM events GROUP BY event", _facts(groups_by_event=True)),
            (
                "grouping by event position",
                "SELECT event, count() FROM events GROUP BY 1",
                _facts(groups_by_event=True),
            ),
            (
                "grouping by event with an event condition",
                "SELECT event, count() FROM events WHERE event IN ('a', 'b') GROUP BY event",
                _facts(),
            ),
            (
                "distinct people over any event",
                f"SELECT count(DISTINCT person_id) FROM events WHERE {_RECENT}",
                _facts(timestamp_bound=True, counts_any_event=True),
            ),
            (
                "unique sessions over any event",
                f"SELECT uniq($session_id) FROM events WHERE {_RECENT}",
                _facts(timestamp_bound=True, counts_any_event=True),
            ),
            (
                "distinct people over one event",
                f"SELECT count(DISTINCT person_id) FROM events WHERE event = 'a' AND {_RECENT}",
                _facts(timestamp_bound=True),
            ),
            (
                "each person's last event",
                "SELECT person_id, max(timestamp) FROM events GROUP BY person_id",
                _facts(counts_any_event=True),
            ),
            (
                "a last-event window",
                "SELECT person_id, row_number() OVER (PARTITION BY person_id ORDER BY timestamp DESC) AS n FROM events",
                _facts(counts_any_event=True),
            ),
            ("the last event", "SELECT max(timestamp) FROM events", _facts()),
            ("a plain count", f"SELECT count() FROM events WHERE {_RECENT}", _facts(timestamp_bound=True)),
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
        mixed = tree_facts(
            self.prepare(
                "SELECT count() FROM events AS e JOIN v_active AS v ON e.person_id = v.person_id WHERE e.event = 'b'"
            )
        )
        assert mixed is not None
        self.assertIsNone(mixed.view_name)
