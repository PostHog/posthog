from collections.abc import Sequence
from dataclasses import replace

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.batch import BatchQueryResult
from posthog.hogql.multi_query import (
    QUERY_SHARING_FLAG,
    ExecutionGroup,
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
                "identifier_group",
                "SELECT distinct_id, count() AS calls FROM events GROUP BY distinct_id ORDER BY calls LIMIT 2",
            ),
            (
                "aliased_identifier_group",
                "SELECT who, count() AS calls FROM (SELECT properties.$session_id AS who FROM events) GROUP BY who ORDER BY calls LIMIT 2",
            ),
            (
                "timestamp_group",
                "SELECT timestamp AS t, count() AS calls FROM events GROUP BY t ORDER BY calls LIMIT 2",
            ),
            (
                "positional_group",
                "SELECT distinct_id AS who, count() AS calls FROM events GROUP BY 1 ORDER BY calls LIMIT 2",
            ),
            (
                "qualified_alias_group",
                "SELECT source.event AS ev, count() AS calls FROM (SELECT distinct_id AS event FROM events) AS source GROUP BY source.event ORDER BY calls LIMIT 2",
            ),
            (
                "outer_alias_shadows_identifier",
                "SELECT source.event AS event, count() AS calls FROM (SELECT distinct_id AS event FROM events) AS source GROUP BY source.event ORDER BY calls LIMIT 2",
            ),
            (
                "outer_alias_shadows_property",
                "SELECT source.event AS event, count() AS calls FROM (SELECT properties.$session_id AS event FROM events) AS source GROUP BY event ORDER BY calls LIMIT 2",
            ),
            (
                "outer_alias_shadows_timestamp",
                "SELECT toDate(timestamp) AS day, count() AS calls FROM (SELECT source.timestamp AS timestamp FROM (SELECT distinct_id AS timestamp FROM events) AS source) GROUP BY day ORDER BY calls LIMIT 2",
            ),
            (
                "aliased_property_group",
                "SELECT event, count() AS calls FROM (SELECT properties.tool AS event FROM events) GROUP BY event ORDER BY calls LIMIT 2",
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

    @parameterized.expand(
        [
            ("day_bucket", "SELECT toDate(timestamp) AS day, count() AS calls FROM events GROUP BY day"),
            (
                "deep_alias_chain",
                "SELECT a40, count() AS calls FROM (SELECT event AS a0, ifNull(a0, a0) AS a1, ifNull(a1, a1) AS a2, ifNull(a2, a2) AS a3, ifNull(a3, a3) AS a4, ifNull(a4, a4) AS a5, ifNull(a5, a5) AS a6, ifNull(a6, a6) AS a7, ifNull(a7, a7) AS a8, ifNull(a8, a8) AS a9, ifNull(a9, a9) AS a10, ifNull(a10, a10) AS a11, ifNull(a11, a11) AS a12, ifNull(a12, a12) AS a13, ifNull(a13, a13) AS a14, ifNull(a14, a14) AS a15, ifNull(a15, a15) AS a16, ifNull(a16, a16) AS a17, ifNull(a17, a17) AS a18, ifNull(a18, a18) AS a19, ifNull(a19, a19) AS a20, ifNull(a20, a20) AS a21, ifNull(a21, a21) AS a22, ifNull(a22, a22) AS a23, ifNull(a23, a23) AS a24, ifNull(a24, a24) AS a25, ifNull(a25, a25) AS a26, ifNull(a26, a26) AS a27, ifNull(a27, a27) AS a28, ifNull(a28, a28) AS a29, ifNull(a29, a29) AS a30, ifNull(a30, a30) AS a31, ifNull(a31, a31) AS a32, ifNull(a32, a32) AS a33, ifNull(a33, a33) AS a34, ifNull(a34, a34) AS a35, ifNull(a35, a35) AS a36, ifNull(a36, a36) AS a37, ifNull(a37, a37) AS a38, ifNull(a38, a38) AS a39, ifNull(a39, a39) AS a40 FROM events) GROUP BY a40",
            ),
            (
                "qualified_passthrough",
                "SELECT source.event AS ev, count() AS calls FROM (SELECT event FROM events) AS source GROUP BY source.event",
            ),
            (
                "derived_from_event",
                "SELECT label, count() AS calls FROM (SELECT if(event = 'a', NULL, event) AS label FROM events) GROUP BY label",
            ),
        ]
    )
    def test_bounded_groupings_share(self, _name: str, base: str) -> None:
        queries = [
            SharingQuery(
                query_id=str(i),
                query=parse_select(f"{base} ORDER BY {order} LIMIT 2"),
                context_key="same-request",
                sharing_enabled=True,
            )
            for i, order in enumerate(("calls DESC", "calls"))
        ]
        self.assertEqual(len(MultiQueryPlanner([SameAggregationTopNRule()]).plan(queries).groups), 1)

    def test_grouped_consumers_keep_their_default_limit(self) -> None:
        class PairRule:
            name = "pair"

            def propose(self, queries: Sequence[SharingQuery]) -> RuleProposals:
                ids = tuple(q.query_id for q in queries)
                return RuleProposals(
                    groups=(ExecutionGroup(query_ids=ids, query=queries[0].query, rule=self.name, router=BothRouter()),)
                )

        class BothRouter:
            def split(self, result: BatchQueryResult) -> dict[str, BatchQueryResult]:
                return {"limited": result, "explicit": result}

        inputs = [
            replace(query, query_id=query_id, default_limit=limit)
            for query, query_id, limit in zip(self.inputs(), ("limited", "explicit"), (2, None))
        ]
        group = MultiQueryPlanner([PairRule()]).plan(inputs).groups[0]
        rows = tuple((f"day-{i}", i) for i in range(5))
        split = group.split(BatchQueryResult(columns=("day", "n"), types=("Date", "UInt64"), rows=rows))
        self.assertEqual(split["limited"].rows, rows[:2])
        self.assertEqual(split["explicit"].rows, rows)

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
