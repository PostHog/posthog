from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
)

from posthog.hogql_queries.experiments.experiment_query_builder import BREAKDOWN_NULL_STRING_LABEL
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentBreakdown(ExperimentQueryRunnerBaseTest):
    @parameterized.expand([("new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_mean_metric_with_breakdown(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - 2 users x 2 browsers
        for i in range(4):
            browser = "Chrome" if i < 2 else "Safari"
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "control",
                    "$feature_flag_response": "control",
                    "$feature_flag": feature_flag.key,
                    "$browser": browser,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: "control",
                    "amount": 10 if browser == "Chrome" else 20,
                    "$browser": browser,
                },
            )

        # Test group - 2 users x 2 browsers
        for i in range(4):
            browser = "Chrome" if i < 2 else "Safari"
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "test",
                    "$feature_flag_response": "test",
                    "$feature_flag": feature_flag.key,
                    "$browser": browser,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: "test",
                    "amount": 15 if browser == "Chrome" else 25,
                    "$browser": browser,
                },
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Verify results are grouped by breakdown
        # We should get results for each variant x breakdown combination
        self.assertIsNotNone(result.baseline)
        self.assertIsNotNone(result.variant_results)

        # Verify breakdown_values is populated (now as list of lists)
        self.assertIsNotNone(result.breakdown_values)
        self.assertEqual(sorted(result.breakdown_values), [["Chrome"], ["Safari"]])

        # Verify breakdown_results is populated with per-breakdown statistics
        self.assertIsNotNone(result.breakdown_results)
        self.assertEqual(len(result.breakdown_results), 2)

        # Verify each breakdown has correct structure (breakdown_value is now a list)
        for breakdown_result in result.breakdown_results:
            self.assertIn(breakdown_result.breakdown_value, [["Chrome"], ["Safari"]])
            self.assertIsNotNone(breakdown_result.baseline)
            self.assertIsNotNone(breakdown_result.variants)
            self.assertGreater(len(breakdown_result.variants), 0)

            # Verify each variant has statistical comparisons
            for variant in breakdown_result.variants:
                self.assertIsNotNone(variant.key)
                self.assertIsNotNone(variant.number_of_samples)

    @parameterized.expand([("new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_breakdown(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="purchase"),
            ],
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - Chrome users complete funnel, Safari users don't
        for i in range(6):
            browser = "Chrome" if i < 3 else "Safari"
            completes_funnel = browser == "Chrome"
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "control",
                    "$feature_flag_response": "control",
                    "$feature_flag": feature_flag.key,
                    "$browser": browser,
                },
            )
            if completes_funnel:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={
                        feature_flag_property: "control",
                        "$browser": browser,
                    },
                )

        # Test group - Safari users complete funnel, Chrome users don't
        for i in range(6):
            browser = "Chrome" if i < 3 else "Safari"
            completes_funnel = browser == "Safari"
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "test",
                    "$feature_flag_response": "test",
                    "$feature_flag": feature_flag.key,
                    "$browser": browser,
                },
            )
            if completes_funnel:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={
                        feature_flag_property: "test",
                        "$browser": browser,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        self.assertIsNotNone(result.baseline)
        self.assertIsNotNone(result.variant_results)

        # Verify breakdown_values is populated (now as list of lists)
        self.assertIsNotNone(result.breakdown_values)
        self.assertEqual(sorted(result.breakdown_values), [["Chrome"], ["Safari"]])

        # Verify breakdown_results is populated with per-breakdown statistics
        self.assertIsNotNone(result.breakdown_results)
        self.assertEqual(len(result.breakdown_results), 2)

        # Verify each breakdown has correct structure (breakdown_value is now a list)
        for breakdown_result in result.breakdown_results:
            self.assertIn(breakdown_result.breakdown_value, [["Chrome"], ["Safari"]])
            self.assertIsNotNone(breakdown_result.baseline)
            self.assertIsNotNone(breakdown_result.variants)
            self.assertGreater(len(breakdown_result.variants), 0)

    @parameterized.expand([("new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_ratio_metric_with_breakdown(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        metric = ExperimentRatioMetric(
            numerator=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            denominator=EventsNode(
                event="view_item",
                math=ExperimentMetricMathType.TOTAL,
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - different ratios per browser
        for i in range(4):
            browser = "Chrome" if i < 2 else "Safari"
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "control",
                    "$feature_flag_response": "control",
                    "$feature_flag": feature_flag.key,
                    "$browser": browser,
                },
            )
            # Numerator
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: "control",
                    "amount": 100,
                    "$browser": browser,
                },
            )
            # Denominator - Chrome gets 2 views, Safari gets 5 views
            view_count = 2 if browser == "Chrome" else 5
            for _ in range(view_count):
                _create_event(
                    team=self.team,
                    event="view_item",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T12:02:00Z",
                    properties={
                        feature_flag_property: "control",
                        "$browser": browser,
                    },
                )

        # Test group
        for i in range(4):
            browser = "Chrome" if i < 2 else "Safari"
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "test",
                    "$feature_flag_response": "test",
                    "$feature_flag": feature_flag.key,
                    "$browser": browser,
                },
            )
            # Numerator
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: "test",
                    "amount": 150,
                    "$browser": browser,
                },
            )
            # Denominator
            view_count = 3 if browser == "Chrome" else 4
            for _ in range(view_count):
                _create_event(
                    team=self.team,
                    event="view_item",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T12:02:00Z",
                    properties={
                        feature_flag_property: "test",
                        "$browser": browser,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        self.assertIsNotNone(result.baseline)
        self.assertIsNotNone(result.variant_results)

        # Verify breakdown_values is populated (now as list of lists)
        self.assertIsNotNone(result.breakdown_values)
        self.assertEqual(sorted(result.breakdown_values), [["Chrome"], ["Safari"]])

        # Verify breakdown_results is populated with per-breakdown statistics
        self.assertIsNotNone(result.breakdown_results)
        self.assertEqual(len(result.breakdown_results), 2)

        # Verify each breakdown has correct structure (breakdown_value is now a list)
        for breakdown_result in result.breakdown_results:
            self.assertIn(breakdown_result.breakdown_value, [["Chrome"], ["Safari"]])
            self.assertIsNotNone(breakdown_result.baseline)
            self.assertIsNotNone(breakdown_result.variants)
            self.assertGreater(len(breakdown_result.variants), 0)

    @parameterized.expand([("new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_mean_metric_with_null_breakdown_values(self, name, use_new_query_builder):
        """Test that NULL breakdown values are handled correctly"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.TOTAL,
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - some users with browser, some without
        for i in range(4):
            has_browser = i < 2
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            exposure_props = {
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
            }
            if has_browser:
                exposure_props["$browser"] = "Chrome"

            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties=exposure_props,
            )

            purchase_props = {feature_flag_property: "control"}
            if has_browser:
                purchase_props["$browser"] = "Chrome"

            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties=purchase_props,
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Should have breakdown values including the NULL label
        self.assertIsNotNone(result.baseline)

        # Verify breakdown_values is populated including NULL label (now as list of lists)
        self.assertIsNotNone(result.breakdown_values)
        self.assertEqual(sorted(result.breakdown_values), sorted([[BREAKDOWN_NULL_STRING_LABEL], ["Chrome"]]))

        # Verify breakdown_results is populated with per-breakdown statistics
        self.assertIsNotNone(result.breakdown_results)
        self.assertEqual(len(result.breakdown_results), 2)

        # Verify each breakdown has correct structure (breakdown_value is now a list)
        for breakdown_result in result.breakdown_results:
            self.assertIn(breakdown_result.breakdown_value, [[BREAKDOWN_NULL_STRING_LABEL], ["Chrome"]])
            self.assertIsNotNone(breakdown_result.baseline)
            self.assertIsNotNone(breakdown_result.variants)
            # variants can be empty if no test variants exist for this breakdown
            self.assertIsInstance(breakdown_result.variants, list)
