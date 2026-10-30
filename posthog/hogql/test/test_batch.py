from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.batch import BatchQueryResult, CountBatchPlanner
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import clone_expr


class TestCountBatchPlanner(SimpleTestCase):
    bounds = "timestamp >= '2026-01-01' AND timestamp < '2026-01-08'"

    def test_split_preserves_missing_groups_column_order_and_names(self) -> None:
        plan = CountBatchPlanner().plan(
            {
                "all": f"SELECT toDate(timestamp) AS day, count() AS n FROM events WHERE {self.bounds} "
                "GROUP BY toDate(timestamp) ORDER BY day DESC",
                "filtered": f"SELECT count() AS filtered, toDate(timestamp) AS date FROM events WHERE {self.bounds} "
                "AND properties.browser = 'Chrome' GROUP BY toDate(timestamp) ORDER BY date DESC",
            }
        )
        self.assertEqual(len(plan.steps), 1)
        results = plan.steps[0].split(
            BatchQueryResult(
                columns=("__batch_day", "__batch_count_0", "__batch_count_1"),
                types=("Date", "UInt64", "UInt64"),
                rows=(("2026-01-02", 2, 0), ("2026-01-01", 3, 1)),
            )
        )
        self.assertEqual(results["all"].rows, (("2026-01-02", 2), ("2026-01-01", 3)))
        self.assertEqual(
            results["filtered"],
            BatchQueryResult(
                columns=("filtered", "date"),
                types=("UInt64", "Date"),
                rows=((1, "2026-01-01"),),
            ),
        )

    @parameterized.expand([("totals", False, ((0,),)), ("groups", True, ())])
    def test_empty_results(self, _name: str, grouped: bool, rows: tuple[tuple[object, ...], ...]) -> None:
        select = "toDate(timestamp) AS day, count()" if grouped else "count()"
        suffix = " GROUP BY toDate(timestamp)" if grouped else ""
        query = f"SELECT {select} FROM events WHERE {self.bounds}{suffix}"
        step = CountBatchPlanner().plan({"a": query, "b": query}).steps[0]
        result = BatchQueryResult(
            columns=("day", "a") if grouped else ("a",),
            types=("Date", "UInt64") if grouped else ("UInt64",),
            rows=rows,
        )
        split = step.split(result)
        self.assertEqual(split["a"].rows, () if grouped else ((0,),))
        self.assertEqual(split["a"], split["b"])

    @parameterized.expand(
        [
            ("limit", "SELECT count() FROM events WHERE {bounds} LIMIT 1"),
            ("having", "SELECT count() FROM events WHERE {bounds} HAVING count() > 1"),
            ("distinct", "SELECT count(DISTINCT distinct_id) FROM events WHERE {bounds}"),
            ("random", "SELECT count() FROM events WHERE {bounds} AND rand() > 1"),
            ("count_expression", "SELECT count(toString(uuid)) FROM events WHERE {bounds}"),
            ("count_random", "SELECT count(rand()) FROM events WHERE {bounds}"),
            ("count_shadow", "SELECT count(created_at) AS created_at FROM events WHERE {bounds}"),
            ("relative", "SELECT count() FROM events WHERE timestamp > now() - INTERVAL 7 DAY"),
            (
                "subquery",
                "SELECT count() FROM events WHERE {bounds} AND distinct_id IN (SELECT distinct_id FROM events)",
            ),
            ("join", "SELECT count() FROM events JOIN persons ON events.person_id = persons.id WHERE {bounds}"),
            ("sample", "SELECT count() FROM events SAMPLE 0.1 WHERE {bounds}"),
            ("shadow_alias", "SELECT count() AS event FROM events WHERE {bounds} AND event = 'purchase'"),
            ("other_aggregate", "SELECT uniqExact(distinct_id) FROM events WHERE {bounds}"),
            ("group_alias", "SELECT toDate(timestamp) AS day, count() FROM events WHERE {bounds} GROUP BY day"),
            (
                "count_order",
                "SELECT toDate(timestamp) AS day, count() AS n FROM events WHERE {bounds} GROUP BY toDate(timestamp) ORDER BY n",
            ),
        ]
    )
    def test_unsupported_queries_remain_intact(self, _name: str, sql: str) -> None:
        query = sql.format(bounds=self.bounds)
        plan = CountBatchPlanner().plan({"a": query, "b": query})
        self.assertEqual(len(plan.steps), 2)
        for step in plan.steps:
            self.assertFalse(step.counts)
            expected = BatchQueryResult(columns=("answer",), types=("UInt64",), rows=((7,),))
            self.assertEqual(step.split(expected), {step.query_ids[0]: expected})

    @parameterized.expand(
        [
            ("different_day", "timestamp >= '2026-01-02' AND timestamp < '2026-01-08'"),
            ("different_hour", "timestamp >= '2026-01-01 01:00:00' AND timestamp < '2026-01-08'"),
            ("exclusive_bound", "timestamp > '2026-01-01' AND timestamp < '2026-01-08'"),
            ("timezone", "timestamp >= toDateTime('2026-01-01', 'America/Los_Angeles') AND timestamp < '2026-01-08'"),
            ("disjoint", "timestamp >= '2026-02-01' AND timestamp < '2026-02-08'"),
            ("no_bounds", "true"),
            ("one_bound", "timestamp >= '2026-01-02'"),
            ("different_event", "event = 'signup'"),
        ]
    )
    def test_different_filters_share_a_scan_without_losing_predicates(self, _name: str, other_bounds: str) -> None:
        plan = CountBatchPlanner().plan(
            {
                "a": f"SELECT count() FROM events WHERE {self.bounds}",
                "b": f"SELECT count() FROM events WHERE {other_bounds}",
            }
        )
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        assert isinstance(step.query, ast.SelectQuery)
        for selected, predicate in zip(step.query.select, (self.bounds, other_bounds)):
            expected = clone_expr(parse_expr(predicate), clear_types=True, clear_locations=True)
            if isinstance(expected, ast.And):
                expected.exprs.sort(key=repr)
            self.assertIsInstance(selected, ast.Alias)
            assert isinstance(selected, ast.Alias)
            self.assertEqual(selected.expr, ast.Call(name="countIf", args=[expected]))
        self.assertEqual(
            set(step.split(BatchQueryResult(columns=("a", "b"), types=("UInt64", "UInt64"), rows=((3, 5),)))),
            {"a", "b"},
        )

    def test_nullable_counts_keep_zero_groups_but_drop_absent_groups(self) -> None:
        plan = CountBatchPlanner().plan(
            {
                "all": "SELECT toDate(timestamp) AS day, count(properties.optional) AS n FROM events GROUP BY toDate(timestamp) ORDER BY day",
                "filtered": "SELECT count(properties.optional) AS n, toDate(timestamp) AS day FROM events WHERE event = 'signup' GROUP BY toDate(timestamp) ORDER BY day",
            }
        )
        self.assertEqual(len(plan.steps), 1)
        split = plan.steps[0].split(
            BatchQueryResult(
                columns=("day", "all_count", "all_presence", "filtered_count", "filtered_presence"),
                types=("Date", "UInt64", "UInt64", "UInt64", "UInt64"),
                rows=(("2026-01-01", 0, 2, 0, 0), ("2026-01-02", 1, 3, 0, 2)),
            )
        )
        self.assertEqual(split["all"].rows, (("2026-01-01", 0), ("2026-01-02", 1)))
        self.assertEqual(split["filtered"].rows, ((0, "2026-01-02"),))
        self.assertEqual(split["filtered"].columns, ("n", "day"))

    @parameterized.expand(
        [
            (
                "overlap",
                "WHERE timestamp >= '2026-01-05' AND timestamp < '2026-01-15'",
                "(timestamp >= '2026-01-01' AND timestamp < '2026-01-10') OR (timestamp >= '2026-01-05' AND timestamp < '2026-01-15')",
            ),
            ("unbounded", "", None),
            ("common_event", "WHERE event = 'signup'", "event = 'signup'"),
        ]
    )
    def test_shared_scan_covers_both_filters(self, name: str, second_where: str, expected_where: str | None) -> None:
        first_where = (
            "event = 'signup' AND timestamp >= '2026-01-01'"
            if name == "common_event"
            else "timestamp >= '2026-01-01' AND timestamp < '2026-01-10'"
        )
        step = (
            CountBatchPlanner()
            .plan(
                {
                    "a": f"SELECT count(uuid) FROM events WHERE {first_where}",
                    "b": f"SELECT count(uuid) FROM events {second_where}",
                }
            )
            .steps[0]
        )
        self.assertEqual(step.query_ids, ("a", "b"))
        assert isinstance(step.query, ast.SelectQuery)
        expected = (
            clone_expr(parse_expr(expected_where), clear_types=True, clear_locations=True) if expected_where else None
        )
        self.assertEqual(step.query.where, expected)

    @parameterized.expand([("uuid", "uuid"), ("property", "properties.$browser")])
    def test_duplicate_counts_share_one_aggregate_and_keep_output_names(self, _name: str, column: str) -> None:
        queries = {str(index): f"SELECT count({column}) AS result_{index} FROM events" for index in range(5)}
        plan = CountBatchPlanner(max_group_size=2).plan(queries)
        self.assertEqual(len(plan.steps), 1)
        assert isinstance(plan.steps[0].query, ast.SelectQuery)
        self.assertEqual(len(plan.steps[0].query.select), 1)
        value = plan.steps[0].query.select[0]
        assert isinstance(value, ast.Alias)
        expected = clone_expr(parse_expr(f"count({column})"), clear_types=True, clear_locations=True)
        self.assertEqual(value.expr, expected)
        split = plan.steps[0].split(BatchQueryResult(columns=("count",), types=("UInt64",), rows=((7,),)))
        for index in range(5):
            self.assertEqual(
                split[str(index)], BatchQueryResult(columns=(f"result_{index}",), types=("UInt64",), rows=((7,),))
            )

    def test_group_size_bound_and_standalone_mode(self) -> None:
        queries = {str(index): f"SELECT count() FROM events WHERE properties.browser = '{index}'" for index in range(5)}
        planner = CountBatchPlanner(max_group_size=2)
        self.assertEqual([len(step.query_ids) for step in planner.plan(queries).steps], [2, 2, 1])
        self.assertEqual(len(planner.plan(queries, combine=False).steps), 5)

    def test_duplicate_nullable_daily_counts_preserve_zero_groups_and_column_order(self) -> None:
        step = (
            CountBatchPlanner()
            .plan(
                {
                    "a": "SELECT count(properties.optional) AS n, toDate(timestamp) AS date FROM events GROUP BY toDate(timestamp) ORDER BY date DESC",
                    "b": "SELECT toDate(timestamp) AS day, count(properties.optional) AS total FROM events GROUP BY toDate(timestamp) ORDER BY day DESC",
                }
            )
            .steps[0]
        )
        self.assertEqual(step.query_ids, ("a", "b"))
        assert isinstance(step.query, ast.SelectQuery)
        self.assertEqual(len(step.query.select), 2)
        split = step.split(
            BatchQueryResult(columns=("day", "count"), types=("Date", "UInt64"), rows=(("2026-01-01", 0),))
        )
        self.assertEqual(
            split["a"], BatchQueryResult(columns=("n", "date"), types=("UInt64", "Date"), rows=((0, "2026-01-01"),))
        )
        self.assertEqual(
            split["b"], BatchQueryResult(columns=("day", "total"), types=("Date", "UInt64"), rows=(("2026-01-01", 0),))
        )

    def test_execution_does_not_mutate_the_plan(self) -> None:
        query = f"SELECT count() AS n FROM events WHERE {self.bounds}"
        plan = CountBatchPlanner().plan({"a": query, "b": query})
        before = repr(plan)

        def runner(tree: ast.SelectQuery | ast.SelectSetQuery) -> BatchQueryResult:
            assert isinstance(tree, ast.SelectQuery)
            tree.where = None
            return BatchQueryResult(columns=("a",), types=("UInt64",), rows=((4,),))

        self.assertEqual(plan.execute(runner)["a"].rows, ((4,),))
        self.assertEqual(repr(plan), before)
