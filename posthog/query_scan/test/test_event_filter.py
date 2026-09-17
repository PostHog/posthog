from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import HogQLQueryExecutor

from posthog.query_scan.event_filter import EventFilterOutcome, classify_event_filter, combine_event_filter
from posthog.query_scan.explain import QueryPlan, parse_query_plan
from posthog.query_scan.test.test_explain import events_read_node, load_plan

_KEY_USED_PLAN = parse_query_plan(load_plan("plan_event_filter_used"))
_KEY_UNUSED_PLAN = parse_query_plan(load_plan("plan_no_event_filter"))
_EVENT_KEY = ["team_id", "toDate(timestamp)", "event"]
# A join whose large read pruned on `event` while its small one did not.
_HEAVIEST_PRUNED_PLAN = parse_query_plan(
    [
        {
            "Plan": {
                "Node Type": "Join",
                "Plans": [
                    events_read_node("true", [], selected_granules=5000, primary_keys=_EVENT_KEY),
                    events_read_node("true", [], selected_granules=10),
                ],
            }
        }
    ]
)


class TestClassifyEventFilter(BaseTest):
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
            ("plain equality", "SELECT count() FROM events WHERE event = 'purchase'", "usable", None),
            ("in a list", "SELECT count() FROM events WHERE event IN ('a', 'b')", "usable", None),
            (
                "inside an or with another condition",
                "SELECT count() FROM events WHERE properties.plan = 'pro' OR event = 'upgrade'",
                "not_used",
                "in_or",
            ),
            (
                "wrapped in a function",
                "SELECT count() FROM events WHERE lower(event) = 'purchase'",
                "not_used",
                "wrapped",
            ),
            ("not equal", "SELECT count() FROM events WHERE event != 'purchase'", "not_used", "negated"),
            ("not in a list", "SELECT count() FROM events WHERE event NOT IN ('$pageview')", "not_used", "negated"),
            (
                "compared to another column",
                "SELECT count() FROM events WHERE event = distinct_id",
                "not_used",
                "dynamic",
            ),
            # A property access prepares to a JSON-extract call, not a bare column, so it lands as a
            # fixed comparison the sort order cannot seek on rather than a dynamic one.
            (
                "compared to a property",
                "SELECT count() FROM events WHERE event = properties.plan",
                "not_used",
                "not_pruned",
            ),
            ("no event condition at all", "SELECT count() FROM events", "none", None),
            (
                "reads that agree",
                "SELECT count() FROM events WHERE event = 'a' UNION ALL SELECT count() FROM events WHERE event = 'b'",
                "usable",
                None,
            ),
            # The tree cannot say which read is the plan's heaviest, so no verdict is pinned to it.
            (
                "reads that disagree",
                "SELECT count() FROM events WHERE event = 'a' UNION ALL SELECT count() FROM events",
                None,
                None,
            ),
        ]
    )
    def test_classification_reads_the_tree(
        self, _name: str, sql: str, expected_class: str | None, expected_reason: str | None
    ) -> None:
        outcome = classify_event_filter(self.prepare(sql))

        if expected_class is None:
            self.assertIsNone(outcome)
            return
        assert outcome is not None
        self.assertEqual(outcome.classification, expected_class)
        self.assertEqual(outcome.reason, expected_reason)


class TestCombineEventFilter(SimpleTestCase):
    @parameterized.expand(
        [
            # A used key overrules a tree fault that is not a negation.
            (
                "key used excuses a wrapped tree",
                EventFilterOutcome(classification="not_used", reason="wrapped"),
                _KEY_USED_PLAN,
                "usable",
                None,
            ),
            # A negation lists `event` in the key yet prunes almost nothing, so the tree stands.
            (
                "key used does not excuse a negated tree",
                EventFilterOutcome(classification="not_used", reason="negated"),
                _KEY_USED_PLAN,
                "not_used",
                "negated",
            ),
            # The plan says no key use while the tree read as usable, so the filter did not prune.
            (
                "key unused faults a usable tree",
                EventFilterOutcome(classification="usable"),
                _KEY_UNUSED_PLAN,
                "not_used",
                "not_pruned",
            ),
            # The advice is about the heaviest read, so a lighter read that did not prune is no fault.
            (
                "the heaviest read's key use decides",
                EventFilterOutcome(classification="usable"),
                _HEAVIEST_PRUNED_PLAN,
                "usable",
                None,
            ),
            # No plan (EXPLAIN failed) leaves the tree verdict untouched.
            (
                "no plan leaves the tree verdict",
                EventFilterOutcome(classification="not_used", reason="in_or"),
                None,
                "not_used",
                "in_or",
            ),
        ]
    )
    def test_the_plan_folds_into_the_tree_verdict(
        self,
        _name: str,
        outcome: EventFilterOutcome,
        plan: QueryPlan | None,
        expected_class: str,
        expected_reason: str | None,
    ) -> None:
        combined = combine_event_filter(outcome, plan)

        self.assertEqual(combined.classification, expected_class)
        self.assertEqual(combined.reason, expected_reason)
