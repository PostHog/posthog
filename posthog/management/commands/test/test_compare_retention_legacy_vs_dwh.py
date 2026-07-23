from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from unittest import TestCase

from parameterized import parameterized

from posthog.schema import QueryTiming, RetentionResult, RetentionValue

from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_OTHER_STRING_LABEL
from posthog.management.commands.compare_retention_legacy_vs_dwh import (
    InsightFinding,
    ResourceStats,
    _cell_is_trailing,
    _clickhouse_seconds,
    _frozen_date_range,
    aggregate_resource_stats,
    attribute_variant_errors,
    build_perf_aggregate,
    classify_insight,
    compute_perf_result,
    diff_retention_results,
    intersect_stable_mismatch,
    parse_query_log_rows,
    referenced_ids,
    summarize_samples,
)

_DT = datetime(2024, 1, 1, tzinfo=UTC)


def _value(count, label, aggregation_value=None):
    return RetentionValue(count=count, label=label, aggregation_value=aggregation_value)


def _result(breakdown_value, label, values):
    return RetentionResult(breakdown_value=breakdown_value, date=_DT, label=label, values=values)


def _simple_series(counts, breakdown_value=None):
    values = [_value(count, f"Day {i}") for i, count in enumerate(counts)]
    return [_result(breakdown_value, "Day 0", values)]


def _insight(query):
    return SimpleNamespace(query=query)


def _retention_query(retention_filter):
    return {"kind": "InsightVizNode", "source": {"kind": "RetentionQuery", "retentionFilter": retention_filter}}


class TestClassifyInsight(TestCase):
    @parameterized.expand(
        [
            ("rolling_24h", {"timeWindowMode": "24_hour_windows"}, "skip", "24h"),
            ("dwh_target", {"targetEntity": {"type": "data_warehouse"}}, "skip", "data_warehouse"),
            ("dwh_returning", {"returningEntity": {"type": "data_warehouse"}}, "skip", "data_warehouse"),
            ("plain_events", {"targetEntity": {"type": "events"}}, "compare", ""),
            ("empty_filter", {}, "compare", ""),
        ]
    )
    def test_classification(self, _name, retention_filter, expected_action, reason_contains):
        action, reason = classify_insight(_insight(_retention_query(retention_filter)))
        self.assertEqual(action, expected_action)
        self.assertIn(reason_contains, reason)

    @parameterized.expand(
        [
            ("query_not_dict", "not a dict"),
            ("wrong_source_kind", {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}}),
            ("missing_retention_filter", {"kind": "InsightVizNode", "source": {"kind": "RetentionQuery"}}),
            ("no_source", {"kind": "InsightVizNode"}),
        ]
    )
    def test_error_classification(self, _name, query):
        action, _reason = classify_insight(_insight(query))
        self.assertEqual(action, "error")


class TestAttributeVariantErrors(TestCase):
    # Mislabeling here inverts the sweep's signal: a DWH-only failure read as ERROR_BOTH (or as
    # legacy's) would hide a rollout blocker behind "broken insight anyway".
    @parameterized.expand(
        [
            ("dwh_only", None, ValueError("boom"), "ERROR_DWH", "ValueError"),
            ("legacy_only", ValueError("boom"), None, "ERROR_LEGACY", "ValueError"),
            ("both_identical", ValueError("boom"), ValueError("boom"), "ERROR_BOTH", "ValueError"),
            ("both_different", ValueError("a"), KeyError("b"), "ERROR_BOTH", "legacy=ValueError, dwh=KeyError"),
        ]
    )
    def test_status_and_type(self, _name, legacy_exc, dwh_exc, expected_status, expected_type):
        status, error_type, summary = attribute_variant_errors(legacy_exc, dwh_exc)
        self.assertEqual(status, expected_status)
        self.assertEqual(error_type, expected_type)
        self.assertTrue(summary)

    def test_identical_failure_summarized_once(self):
        _status, _error_type, summary = attribute_variant_errors(ValueError("boom"), ValueError("boom"))
        self.assertIn("identically", summary)
        self.assertEqual(summary.count("boom"), 1)

    def test_differing_failures_both_summarized(self):
        _status, _error_type, summary = attribute_variant_errors(ValueError("legacy msg"), TypeError("dwh msg"))
        self.assertIn("legacy msg", summary)
        self.assertIn("dwh msg", summary)


class TestReferencedIds(TestCase):
    # A missed reference site keeps a broken insight erroring instead of skipping; over-collection
    # (event breakdowns, "all"/0 pseudo-cohort) would wrongly skip healthy insights, silently
    # shrinking sweep coverage.
    @parameterized.expand(
        [
            (
                "action_entities",
                {
                    "retentionFilter": {
                        "targetEntity": {"type": "actions", "id": "123"},
                        "returningEntity": {"type": "actions", "id": 456},
                    }
                },
                {123, 456},
                set(),
            ),
            (
                "event_entities_have_no_refs",
                {"retentionFilter": {"targetEntity": {"type": "events", "id": "$pageview"}}},
                set(),
                set(),
            ),
            (
                "cohort_in_nested_property_group",
                {
                    "properties": {
                        "type": "AND",
                        "values": [{"type": "OR", "values": [{"key": "id", "type": "cohort", "value": 27777}]}],
                    }
                },
                set(),
                {27777},
            ),
            (
                "cohort_on_entity_properties",
                {
                    "retentionFilter": {
                        "targetEntity": {
                            "type": "events",
                            "properties": [{"key": "id", "type": "cohort", "value": 18217}],
                        }
                    }
                },
                set(),
                {18217},
            ),
            (
                "cohort_breakdown_uses_property_key",
                {"breakdownFilter": {"breakdowns": [{"type": "cohort", "property": 18217}]}},
                set(),
                {18217},
            ),
            (
                "legacy_single_breakdown_with_all_pseudo_cohort",
                {"breakdownFilter": {"breakdown_type": "cohort", "breakdown": [123, "all", 0]}},
                set(),
                {123},
            ),
            (
                "event_breakdown_property_is_not_a_cohort",
                {"breakdownFilter": {"breakdowns": [{"type": "event", "property": "42"}]}},
                set(),
                set(),
            ),
        ]
    )
    def test_extraction(self, _name, source, expected_actions, expected_cohorts):
        action_ids, cohort_ids = referenced_ids({"kind": "RetentionQuery", **source})
        self.assertEqual(action_ids, expected_actions)
        self.assertEqual(cohort_ids, expected_cohorts)


class TestDiffRetentionResults(TestCase):
    def test_identical_is_ok(self):
        diff = diff_retention_results(_simple_series([10, 5, 2]), _simple_series([10, 5, 2]))
        self.assertEqual(diff.status, "OK")
        self.assertEqual(diff.cell_diffs, [])

    def test_count_within_relative_tolerance_is_ok(self):
        diff = diff_retention_results(_simple_series([1000]), _simple_series([1001]), count_tol_rel=0.01)
        self.assertEqual(diff.status, "OK")

    def test_count_beyond_tolerance_is_mismatch(self):
        diff = diff_retention_results(_simple_series([100, 50]), _simple_series([100, 40]))
        self.assertEqual(diff.status, "MISMATCH")
        self.assertEqual(len(diff.cell_diffs), 1)
        cell = diff.cell_diffs[0]
        self.assertEqual(cell.field, "count")
        self.assertEqual(cell.legacy, 50)
        self.assertEqual(cell.dwh, 40)
        self.assertEqual(cell.abs_diff, 10)
        assert cell.rel_diff is not None
        self.assertAlmostEqual(cell.rel_diff, -0.2)

    def test_aggregation_value_diff_is_mismatch(self):
        legacy = [_result(None, "Day 0", [_value(10, "Day 0", aggregation_value=100.0)])]
        dwh = [_result(None, "Day 0", [_value(10, "Day 0", aggregation_value=130.0)])]
        diff = diff_retention_results(legacy, dwh)
        self.assertEqual(diff.status, "MISMATCH")
        self.assertEqual(diff.cell_diffs[0].field, "aggregation_value")

    def test_cell_diffs_sorted_by_abs_diff(self):
        legacy = _simple_series([100, 100, 100])
        dwh = _simple_series([90, 100, 50])
        diff = diff_retention_results(legacy, dwh)
        self.assertEqual([c.abs_diff for c in diff.cell_diffs], [50, 10])

    def test_breakdown_set_diff_and_other_bucket(self):
        legacy = _simple_series([10], breakdown_value="chrome") + _simple_series([5], breakdown_value="firefox")
        dwh = _simple_series([10], breakdown_value="chrome") + _simple_series(
            [5], breakdown_value=BREAKDOWN_OTHER_STRING_LABEL
        )
        diff = diff_retention_results(legacy, dwh)
        self.assertEqual(diff.status, "MISMATCH")
        self.assertEqual(diff.breakdown_only_legacy, ["firefox"])
        self.assertEqual(diff.breakdown_only_dwh, [BREAKDOWN_OTHER_STRING_LABEL])
        self.assertTrue(diff.other_bucket_changed)

    def test_row_count_mismatch(self):
        diff = diff_retention_results(_simple_series([10]), [])
        self.assertEqual(diff.status, "MISMATCH")
        self.assertEqual(diff.row_count_legacy, 1)
        self.assertEqual(diff.row_count_dwh, 0)

    def test_row_label_mismatch_with_equal_counts_is_flagged(self):
        # Equal row counts and identical breakdown sets, but a differing row label must not be
        # silently dropped into an OK verdict.
        legacy = [_result(None, "Day 0", [_value(10, "Day 0")]), _result(None, "Day 1", [_value(5, "Day 0")])]
        dwh = [_result(None, "Day 0", [_value(10, "Day 0")]), _result(None, "Day 2", [_value(5, "Day 0")])]
        diff = diff_retention_results(legacy, dwh)
        self.assertEqual(diff.status, "MISMATCH")
        self.assertTrue(any("missing in DWH" in note for note in diff.notes))
        self.assertTrue(any("missing in legacy" in note for note in diff.notes))


class TestTrailingClassification(TestCase):
    def test_trailing_only_diff_is_ok(self):
        # Cohort interval == latest interval, so every cell in the row is trailing: a count delta is
        # live-ingest drift, not a mismatch.
        diff = diff_retention_results(
            _simple_series([100, 50]),
            _simple_series([100, 40]),
            latest_interval_start=_DT,
            interval_delta=timedelta(days=1),
        )
        self.assertEqual(diff.status, "OK")
        self.assertEqual(diff.cell_diffs, [])
        self.assertEqual(len(diff.trailing_cell_diffs), 1)
        self.assertEqual(diff.trailing_cell_diffs[0].value_label, "Day 1")

    def test_returning_offset_routes_per_cell(self):
        # Cohort at _DT, latest interval three periods later: the offset-3 returning bucket is trailing,
        # the offset-0 one is not. Each cell is routed independently.
        legacy = [_result(None, "Day 0", [_value(10, f"Day {i}") for i in range(4)])]
        dwh = [
            _result(None, "Day 0", [_value(5, "Day 0"), _value(10, "Day 1"), _value(10, "Day 2"), _value(7, "Day 3")])
        ]
        diff = diff_retention_results(
            legacy, dwh, latest_interval_start=_DT + timedelta(days=3), interval_delta=timedelta(days=1)
        )
        self.assertEqual(diff.status, "MISMATCH")
        self.assertEqual([c.value_label for c in diff.cell_diffs], ["Day 0"])
        self.assertEqual([c.value_label for c in diff.trailing_cell_diffs], ["Day 3"])

    def test_non_trailing_cell_diff_is_mismatch(self):
        diff = diff_retention_results(
            _simple_series([100, 50]),
            _simple_series([100, 40]),
            latest_interval_start=_DT + timedelta(days=2),
            interval_delta=timedelta(days=1),
        )
        self.assertEqual(diff.status, "MISMATCH")
        self.assertEqual(len(diff.cell_diffs), 1)
        self.assertEqual(diff.trailing_cell_diffs, [])

    def test_classification_disabled_by_default(self):
        # Without the trailing params, behaviour is identical to before: everything counts.
        diff = diff_retention_results(_simple_series([100, 50]), _simple_series([100, 40]))
        self.assertEqual(diff.status, "MISMATCH")
        self.assertEqual(len(diff.cell_diffs), 1)
        self.assertEqual(diff.trailing_cell_diffs, [])

    @parameterized.expand(
        [
            ("latest_none", _DT, 0, None, timedelta(days=1), False),
            ("cohort_none", None, 0, _DT, timedelta(days=1), False),
            ("cohort_equals_latest", _DT, 2, _DT, timedelta(days=1), True),
            ("returning_equals_latest", _DT, 3, _DT + timedelta(days=3), timedelta(days=1), True),
            ("returning_off_by_one", _DT, 2, _DT + timedelta(days=3), timedelta(days=1), False),
            ("offset_branch_needs_delta", _DT, 3, _DT + timedelta(days=3), None, False),
        ]
    )
    def test_cell_is_trailing(self, _name, cohort_date, offset, latest, delta, expected):
        self.assertEqual(_cell_is_trailing(cohort_date, offset, latest, delta), expected)


class TestIntersectStableMismatch(TestCase):
    def test_transient_mismatch_dropped(self):
        first = diff_retention_results(_simple_series([100, 50]), _simple_series([100, 40]))
        second = diff_retention_results(_simple_series([100, 50]), _simple_series([100, 50]))
        result = intersect_stable_mismatch(first, second)
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.cell_diffs, [])

    def test_reproduced_mismatch_kept(self):
        first = diff_retention_results(_simple_series([100, 50]), _simple_series([100, 40]))
        second = diff_retention_results(_simple_series([100, 50]), _simple_series([100, 40]))
        result = intersect_stable_mismatch(first, second)
        self.assertEqual(result.status, "MISMATCH")
        self.assertEqual(len(result.cell_diffs), 1)
        self.assertEqual(result.cell_diffs[0].value_label, "Day 1")

    def test_reproduced_row_count_mismatch_kept(self):
        first = diff_retention_results(_simple_series([10]), [])
        second = diff_retention_results(_simple_series([10]), [])
        result = intersect_stable_mismatch(first, second)
        self.assertEqual(result.status, "MISMATCH")

    def test_transient_breakdown_divergence_dropped(self):
        first = diff_retention_results(
            _simple_series([10], breakdown_value="chrome") + _simple_series([5], breakdown_value="firefox"),
            _simple_series([10], breakdown_value="chrome")
            + _simple_series([5], breakdown_value=BREAKDOWN_OTHER_STRING_LABEL),
        )
        self.assertEqual(first.status, "MISMATCH")
        second = diff_retention_results(
            _simple_series([10], breakdown_value="chrome") + _simple_series([5], breakdown_value="firefox"),
            _simple_series([10], breakdown_value="chrome") + _simple_series([5], breakdown_value="firefox"),
        )
        result = intersect_stable_mismatch(first, second)
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.breakdown_only_dwh, [])
        self.assertFalse(result.other_bucket_changed)

    def test_trailing_diffs_carried_through(self):
        legacy = [_result(None, "Day 0", [_value(10, f"Day {i}") for i in range(4)])]
        dwh = [
            _result(None, "Day 0", [_value(5, "Day 0"), _value(10, "Day 1"), _value(10, "Day 2"), _value(7, "Day 3")])
        ]
        latest = _DT + timedelta(days=3)
        delta = timedelta(days=1)
        first = diff_retention_results(legacy, dwh, latest_interval_start=latest, interval_delta=delta)
        second = diff_retention_results(legacy, dwh, latest_interval_start=latest, interval_delta=delta)
        result = intersect_stable_mismatch(first, second)
        self.assertEqual(result.status, "MISMATCH")
        self.assertEqual(result.trailing_cell_diffs, first.trailing_cell_diffs)
        self.assertEqual([c.value_label for c in result.trailing_cell_diffs], ["Day 3"])


class TestFrozenDateRange(TestCase):
    def test_excludes_current_period(self):
        frozen = _frozen_date_range(_DT, _DT + timedelta(days=3), timedelta(days=1))
        self.assertEqual(frozen["date_from"], _DT.isoformat())
        self.assertEqual(frozen["date_to"], (_DT + timedelta(days=2)).isoformat())
        self.assertTrue(frozen["explicitDate"])


class TestClickhouseSeconds(TestCase):
    def test_matches_leaf_key(self):
        timings = [
            QueryTiming(k="./retention_query/print_ast", t=0.5),
            QueryTiming(k="./retention_query/.../clickhouse_execute", t=0.12),
        ]
        self.assertAlmostEqual(_clickhouse_seconds(timings), 0.12)

    def test_sums_multiple_clickhouse_execute(self):
        timings = [
            QueryTiming(k="./a/clickhouse_execute", t=0.1),
            QueryTiming(k="./b/clickhouse_execute", t=0.2),
        ]
        self.assertAlmostEqual(_clickhouse_seconds(timings), 0.3)

    def test_accepts_dicts(self):
        self.assertAlmostEqual(_clickhouse_seconds([{"k": "x/clickhouse_execute", "t": 0.25}]), 0.25)

    @parameterized.expand([("none", None), ("empty", [])])
    def test_empty(self, _name, timings):
        self.assertEqual(_clickhouse_seconds(timings), 0.0)


class TestSummarizeSamples(TestCase):
    def test_known_array(self):
        timing = summarize_samples([10, 20, 30, 40, 50])
        self.assertEqual(timing.min_ms, 10)
        self.assertEqual(timing.median_ms, 30)
        self.assertAlmostEqual(timing.p95_ms, 48.0)
        self.assertAlmostEqual(timing.stdev_ms, 15.8113883, places=5)

    def test_single_sample_has_zero_stdev(self):
        timing = summarize_samples([42.0])
        self.assertEqual(timing.min_ms, 42.0)
        self.assertEqual(timing.median_ms, 42.0)
        self.assertEqual(timing.stdev_ms, 0.0)

    def test_empty(self):
        timing = summarize_samples([])
        self.assertEqual(timing.median_ms, 0.0)


class TestComputePerfResult(TestCase):
    @parameterized.expand(
        [
            # name, wall_legacy, wall_dwh, ch_legacy, ch_dwh, rel, ms, ratio, is_regression, is_improvement
            (
                "regression",
                [100, 100, 100],
                [200, 200, 200],
                [80, 80, 80],
                [180, 180, 180],
                0.10,
                50.0,
                2.0,
                True,
                False,
            ),
            ("slowdown_below_ms_floor", [10, 10], [20, 20], [5, 5], [10, 10], 0.10, 50.0, 2.0, False, False),
            ("improvement", [200, 200], [100, 100], [180, 180], [90, 90], 0.10, 50.0, 0.5, False, True),
            ("zero_legacy_median", [0, 0], [10, 10], [0, 0], [10, 10], 0.10, 1.0, None, False, False),
        ]
    )
    def test_compute_perf_result(
        self,
        _name,
        wall_legacy,
        wall_dwh,
        ch_legacy,
        ch_dwh,
        rel,
        ms,
        expected_ratio,
        expected_regression,
        expected_improvement,
    ):
        result = compute_perf_result(wall_legacy, wall_dwh, ch_legacy, ch_dwh, regression_rel=rel, regression_ms=ms)
        self.assertEqual(result.ratio_median_wall, expected_ratio)
        self.assertEqual(result.is_regression, expected_regression)
        self.assertEqual(result.is_improvement, expected_improvement)


class TestResourceStats(TestCase):
    def test_parse_query_log_rows(self):
        rows = [("42_x_a", 1000, 50, 9000, 12, 1), ("42_x_b", 2000, 80, 7000, 8, 1)]
        stats = parse_query_log_rows(rows)
        self.assertEqual(stats["42_x_a"].read_bytes, 1000)
        self.assertEqual(stats["42_x_b"].read_rows, 80)

    def test_aggregate_sums_bytes_and_rows_max_memory(self):
        stats_by_id = {
            "a": ResourceStats(
                read_bytes=1000, read_rows=50, memory_usage=9000, query_duration_ms=12, ch_query_count=1
            ),
            "b": ResourceStats(read_bytes=2000, read_rows=80, memory_usage=7000, query_duration_ms=8, ch_query_count=1),
        }
        aggregated = aggregate_resource_stats(["a", "b"], stats_by_id)
        assert aggregated is not None
        self.assertEqual(aggregated.read_bytes, 3000)
        self.assertEqual(aggregated.read_rows, 130)
        self.assertEqual(aggregated.memory_usage, 9000)
        self.assertEqual(aggregated.ch_query_count, 2)

    def test_aggregate_returns_none_without_matches(self):
        self.assertIsNone(aggregate_resource_stats(["missing"], {}))


class TestBuildPerfAggregate(TestCase):
    def _finding_with_perf(self, insight_id, wall_legacy, wall_dwh, read_legacy=None, read_dwh=None):
        finding = InsightFinding(
            insight_id=insight_id,
            short_id=f"s{insight_id}",
            team_id=1,
            name="",
            url="",
            status="OK",
        )
        finding.perf = compute_perf_result(
            wall_legacy, wall_dwh, wall_legacy, wall_dwh, regression_rel=0.10, regression_ms=50.0
        )
        if read_legacy is not None and read_dwh is not None:
            finding.resource_legacy = ResourceStats(read_legacy, 0, 0, 0, 1)
            finding.resource_dwh = ResourceStats(read_dwh, 0, 0, 0, 1)
            finding.bytes_ratio = read_dwh / read_legacy
        return finding

    def test_distribution_and_regression_counts(self):
        findings = [
            self._finding_with_perf(1, [100, 100], [300, 300], read_legacy=1000, read_dwh=3000),  # regression
            self._finding_with_perf(2, [100, 100], [100, 100], read_legacy=1000, read_dwh=1000),  # even
            self._finding_with_perf(3, [200, 200], [100, 100], read_legacy=2000, read_dwh=1000),  # improvement
        ]
        aggregate = build_perf_aggregate(findings, worst_n=5)
        self.assertEqual(aggregate.n_compared, 3)
        self.assertEqual(aggregate.n_regressions, 1)
        self.assertEqual(aggregate.n_improvements, 1)
        self.assertEqual(aggregate.wall_ratio_dist["median"], 1.0)
        self.assertEqual(aggregate.worst_by_rel[0].insight_id, 1)
