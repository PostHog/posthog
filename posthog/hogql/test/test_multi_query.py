from collections.abc import Sequence
from dataclasses import replace

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.batch import BatchQueryResult
from posthog.hogql.multi_query import (
    QUERY_SHARING_FLAG,
    MultiQueryPlanner,
    RuleProposals,
    SharingQuery,
    execute_group,
    is_query_sharing_enabled,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.sharing_rules import CountFusionRule, SameAggregationTopNRule
from posthog.hogql.visitor import clone_expr


class TestMultiQueryPlanner(SimpleTestCase):
    base = "SELECT event, count() AS calls, uniqExact(distinct_id) AS people FROM events GROUP BY event"

    def inputs(self, second: str | None = None, context_key: str = "same-request") -> list[SharingQuery]:
        return [
            SharingQuery(
                query_id="calls",
                query=parse_select(self.base + " ORDER BY calls DESC, event LIMIT 2"),
                context_key="same-request",
                sharing_enabled=True,
            ),
            SharingQuery(
                query_id="people",
                query=parse_select(second or self.base + " ORDER BY people DESC, event LIMIT 1"),
                context_key=context_key,
                sharing_enabled=True,
            ),
        ]

    def test_top_n_routes_ordered_rows_and_preserves_input(self) -> None:
        inputs = self.inputs()
        originals = [clone_expr(q.query) for q in inputs]
        plan = MultiQueryPlanner([SameAggregationTopNRule()]).plan(inputs)
        self.assertEqual(len(plan.groups), 1)
        group = plan.groups[0]
        result = BatchQueryResult(
            columns=("event", "calls", "people", "consumer", "rank"),
            types=("String", "UInt64", "UInt64", "UInt8", "UInt64"),
            rows=(("action_a", 12, 2, 0, 1), ("action_b", 9, 8, 0, 2), ("action_b", 9, 8, 1, 1)),
        )
        split = execute_group(group, lambda _: result)
        self.assertEqual(
            split["calls"],
            BatchQueryResult(
                columns=("event", "calls", "people"),
                types=("String", "UInt64", "UInt64"),
                rows=(("action_a", 12, 2), ("action_b", 9, 8)),
            ),
        )
        self.assertEqual(split["people"].rows, (("action_b", 9, 8),))
        self.assertEqual([q.query for q in inputs], originals)
        empty = group.split(BatchQueryResult(columns=result.columns, types=result.types, rows=()))
        self.assertEqual(empty["calls"].rows, ())
        self.assertEqual(empty["people"].rows, ())

    @parameterized.expand(
        [
            (
                "filter",
                "SELECT event, count() AS calls, uniqExact(distinct_id) AS people FROM events WHERE event = 'other' GROUP BY event ORDER BY calls DESC LIMIT 2",
            ),
            (
                "volatile",
                "SELECT event, count() AS calls, uniqExact(distinct_id) AS people FROM events WHERE rand() > 0 GROUP BY event ORDER BY calls DESC LIMIT 2",
            ),
            (
                "relative_time",
                "SELECT event, count() AS calls, uniqExact(distinct_id) AS people FROM events WHERE timestamp < now() GROUP BY event ORDER BY calls DESC LIMIT 2",
            ),
            ("with_ties", base + " ORDER BY calls DESC LIMIT 2 WITH TIES"),
            ("offset", base + " ORDER BY calls DESC LIMIT 2 OFFSET 1"),
            ("no_limit", base + " ORDER BY calls DESC"),
            ("rank_expression", base + " ORDER BY calls + people LIMIT 2"),
            (
                "unaliased_property",
                "SELECT properties.tool, count() AS calls FROM events GROUP BY properties.tool ORDER BY calls LIMIT 2",
            ),
            (
                "wildcard",
                "SELECT *, count() AS calls FROM (SELECT event FROM events) GROUP BY event ORDER BY calls LIMIT 2",
            ),
            (
                "positional_order",
                "SELECT event, 1 AS one, count() AS calls FROM events GROUP BY event ORDER BY 1 LIMIT 2",
            ),
            (
                "reserved_alias",
                "SELECT event AS __sharing_consumer, count() AS calls FROM events GROUP BY event ORDER BY calls LIMIT 2",
            ),
            ("opaque_view", "SELECT event, count() AS calls FROM saved_view GROUP BY event ORDER BY calls LIMIT 2"),
            (
                "nested_volatile",
                "SELECT event, count() AS calls FROM (SELECT event FROM events WHERE rand() > 0) GROUP BY event ORDER BY calls LIMIT 2",
            ),
            (
                "nested_limit",
                "SELECT event, count() AS calls FROM (SELECT event FROM events LIMIT 10) GROUP BY event ORDER BY calls LIMIT 2",
            ),
            (
                "predicate_subquery",
                "SELECT event, count() AS calls FROM events WHERE event IN (SELECT event FROM events) GROUP BY event ORDER BY calls LIMIT 2",
            ),
            (
                "window",
                "SELECT event, count() AS calls, row_number() OVER () AS r FROM events GROUP BY event ORDER BY calls LIMIT 2",
            ),
        ]
    )
    def test_unsupported_or_different_queries_run_separately(self, _name: str, second: str) -> None:
        inputs = self.inputs(second)
        plan = MultiQueryPlanner([SameAggregationTopNRule()]).plan(inputs)
        self.assertEqual([g.query_ids for g in plan.groups], [("calls",), ("people",)])
        self.assertTrue(plan.rejections)
        for group, original in zip(plan.groups, inputs):
            self.assertEqual(group.query, clone_expr(original.query, clear_types=True, clear_locations=True))
        identical = [
            SharingQuery(query_id=str(i), query=parse_select(second), context_key="same-request", sharing_enabled=True)
            for i in range(2)
        ]
        if _name != "filter":
            self.assertEqual(len(MultiQueryPlanner([SameAggregationTopNRule()]).plan(identical).groups), 2)

    def test_context_isolation_and_rule_composition(self) -> None:
        planner = MultiQueryPlanner([SameAggregationTopNRule(), CountFusionRule()])
        self.assertEqual(len(planner.plan(self.inputs(context_key="different-permissions")).groups), 2)
        inputs = [
            *self.inputs(),
            SharingQuery(
                query_id="total",
                query=parse_select("SELECT count() FROM events"),
                context_key="same-request",
                sharing_enabled=True,
            ),
            SharingQuery(
                query_id="filtered",
                query=parse_select("SELECT count() FROM events WHERE event = 'other'"),
                context_key="same-request",
                sharing_enabled=True,
            ),
            SharingQuery(
                query_id="single",
                query=parse_select("SELECT event FROM events LIMIT 1"),
                context_key="same-request",
                sharing_enabled=True,
            ),
        ]
        plan = planner.plan(inputs)
        self.assertEqual([g.rule for g in plan.groups], ["same_aggregation_top_n", "count_fusion", "separate"])
        self.assertEqual([g.query_ids for g in plan.groups], [("calls", "people"), ("total", "filtered"), ("single",)])
        self.assertEqual(len(planner.plan(inputs, combine=False).groups), 5)

    @parameterized.expand([(False, False), (True, False), (False, True), (True, True)])
    def test_only_enabled_inputs_can_share(self, first_enabled: bool, second_enabled: bool) -> None:
        inputs = [
            replace(query, sharing_enabled=enabled)
            for query, enabled in zip(self.inputs(), (first_enabled, second_enabled))
        ]
        plan = MultiQueryPlanner([SameAggregationTopNRule()]).plan(inputs)
        self.assertEqual(len(plan.groups), 1 if first_enabled and second_enabled else 2)
        default_disabled = [SharingQuery(query_id=q.query_id, query=q.query, context_key=q.context_key) for q in inputs]
        self.assertEqual(len(MultiQueryPlanner([SameAggregationTopNRule()]).plan(default_disabled).groups), 2)

    @parameterized.expand(
        [(True, True), (False, False), (None, False), ("on", False), (RuntimeError("unavailable"), False)]
    )
    def test_feature_flag_fails_closed(self, value: bool | str | None | RuntimeError, enabled: bool) -> None:
        team = Mock(uuid="synthetic-project", pk=7, organization_id="synthetic-organization")
        with patch("posthog.hogql.multi_query.posthoganalytics.feature_enabled") as flag:
            if isinstance(value, RuntimeError):
                flag.side_effect = value
            else:
                flag.return_value = value
            self.assertEqual(is_query_sharing_enabled(team), enabled)
        flag.assert_called_once_with(
            QUERY_SHARING_FLAG,
            "synthetic-project",
            groups={"organization": "synthetic-organization", "project": "7"},
            group_properties={"organization": {"id": "synthetic-organization"}, "project": {"id": "7"}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    @parameterized.expand(
        [
            ("wrong_consumer", (("a", 1, 1, 2, 1),)),
            ("wrong_rank", (("a", 1, 1, 0, 2),)),
            ("too_many", (("a", 1, 1, 1, 1), ("b", 1, 1, 1, 2))),
            ("truncated_schema", (("a", 1, 1),)),
        ]
    )
    def test_invalid_routing_results_fail_closed(self, _name: str, rows: tuple[tuple[object, ...], ...]) -> None:
        group = MultiQueryPlanner([SameAggregationTopNRule()]).plan(self.inputs()).groups[0]
        with self.assertRaises(ValueError):
            group.split(
                BatchQueryResult(
                    columns=("event", "calls", "people", "consumer", "rank"),
                    types=("String", "UInt64", "UInt64", "UInt8", "UInt64"),
                    rows=rows,
                )
            )

    def test_invalid_rule_cannot_claim_queries_twice(self) -> None:
        class OverlappingRule:
            name = "overlap"

            def propose(self, queries: Sequence[SharingQuery]) -> RuleProposals:
                valid = SameAggregationTopNRule().propose(queries)
                return RuleProposals(groups=valid.groups + valid.groups)

        with self.assertRaisesRegex(ValueError, "overlapping proposal"):
            MultiQueryPlanner([OverlappingRule()]).plan(self.inputs())
        with self.assertRaisesRegex(ValueError, "unique"):
            MultiQueryPlanner([]).plan(self.inputs() * 2)
        with self.assertRaisesRegex(ValueError, "planning limit"):
            MultiQueryPlanner([], max_queries=1).plan(self.inputs())
