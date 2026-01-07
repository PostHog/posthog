from datetime import datetime
from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries
from unittest import skip

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    FunnelConversionWindowTimeUnit,
    StartHandling,
)

from posthog.hogql_queries.experiments.experiment_query_builder import BREAKDOWN_NULL_STRING_LABEL
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
import pytest


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentBreakdown(ExperimentQueryRunnerBaseTest):
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_mean_metric_with_breakdown(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
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
        assert result.baseline is not None
        assert result.variant_results is not None

        # Verify breakdown_results is populated with per-breakdown statistics
        assert result.breakdown_results is not None
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 2

        # Verify each breakdown has correct structure (breakdown_value is now a list)
        for breakdown_result in result.breakdown_results:
            assert breakdown_result.breakdown_value in [["Chrome"], ["Safari"]]
            assert breakdown_result.baseline is not None
            assert breakdown_result.variants is not None
            assert len(breakdown_result.variants) > 0

            # Verify each variant has statistical comparisons
            for variant in breakdown_result.variants:
                assert variant.key is not None
                assert variant.number_of_samples is not None

    @parameterized.expand([("new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_mean_metric_breakdown_with_changing_property_values(self, name, use_new_query_builder):
        """
        Regression test for bug where users with different breakdown values across exposures
        were counted multiple times (once per unique breakdown value).

        Tests that users with multiple exposure events having different breakdown property
        values are attributed to the breakdown value from their FIRST exposure only.
        """
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

        # Control user who changes browser between exposures
        _create_person(distinct_ids=["user_control_changing"], team_id=self.team.pk)

        # First exposure with Chrome at 12:00
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_control_changing",
            timestamp="2020-01-02T12:00:00Z",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
                "$browser": "Chrome",
            },
        )

        # Second exposure with Safari at 13:00 (user switched browser)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_control_changing",
            timestamp="2020-01-02T13:00:00Z",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
                "$browser": "Safari",
            },
        )

        # Purchase event at 14:00
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_control_changing",
            timestamp="2020-01-02T14:00:00Z",
            properties={
                feature_flag_property: "control",
                "amount": 100,
                "$browser": "Safari",
            },
        )

        # Control user with consistent browser
        _create_person(distinct_ids=["user_control_consistent"], team_id=self.team.pk)

        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_control_consistent",
            timestamp="2020-01-02T12:00:00Z",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
                "$browser": "Firefox",
            },
        )

        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_control_consistent",
            timestamp="2020-01-02T14:00:00Z",
            properties={
                feature_flag_property: "control",
                "amount": 50,
                "$browser": "Firefox",
            },
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Verify results
        assert result.breakdown_results is not None
        assert result.breakdown_results is not None

        # Should have 2 breakdown categories (Chrome and Firefox)
        # NOT 3 (Chrome, Safari, Firefox) even though changing user had Safari exposure
        # The user should be attributed to Chrome (first exposure)
        assert len(result.breakdown_results) == 2

        breakdown_values = [br.breakdown_value for br in result.breakdown_results]
        assert ["Chrome"] in breakdown_values
        assert ["Firefox"] in breakdown_values
        # Safari should NOT appear as a breakdown
        assert ["Safari"] not in breakdown_values

        # Find Chrome breakdown (has the changing user)
        chrome_breakdown = next(br for br in result.breakdown_results if br.breakdown_value == ["Chrome"])
        assert chrome_breakdown.baseline is not None

        # Should have exactly 1 user in Chrome (the changing user, attributed to first exposure)
        assert chrome_breakdown.baseline.number_of_samples == 1
        assert chrome_breakdown.baseline.sum == 100  # Their purchase amount

        # Find Firefox breakdown (has the consistent user)
        firefox_breakdown = next(br for br in result.breakdown_results if br.breakdown_value == ["Firefox"])
        assert firefox_breakdown.baseline.number_of_samples == 1
        assert firefox_breakdown.baseline.sum == 50

    @parameterized.expand([("new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_breakdown(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
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

        assert result.baseline is not None
        assert result.variant_results is not None

        # Verify breakdown_results is populated with per-breakdown statistics
        assert result.breakdown_results is not None
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 2

        # Verify each breakdown has correct structure (breakdown_value is now a list)
        for breakdown_result in result.breakdown_results:
            assert breakdown_result.breakdown_value in [["Chrome"], ["Safari"]]
            assert breakdown_result.baseline is not None
            assert breakdown_result.variants is not None
            assert len(breakdown_result.variants) > 0

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_ratio_metric_with_breakdown(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
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

        assert result.baseline is not None
        assert result.variant_results is not None

        # Verify breakdown_results is populated with per-breakdown statistics
        assert result.breakdown_results is not None
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 2

        # Verify each breakdown has correct structure (breakdown_value is now a list)
        for breakdown_result in result.breakdown_results:
            assert breakdown_result.breakdown_value in [["Chrome"], ["Safari"]]
            assert breakdown_result.baseline is not None
            assert breakdown_result.variants is not None
            assert len(breakdown_result.variants) > 0

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_mean_metric_with_null_breakdown_values(self):
        """Test that NULL breakdown values are handled correctly"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
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
        assert result.baseline is not None

        # Verify breakdown_results is populated with per-breakdown statistics
        assert result.breakdown_results is not None
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 2

        # Verify each breakdown has correct structure (breakdown_value is now a list)
        for breakdown_result in result.breakdown_results:
            assert breakdown_result.breakdown_value in [[BREAKDOWN_NULL_STRING_LABEL], ["Chrome"]]
            assert breakdown_result.baseline is not None
            assert breakdown_result.variants is not None
            # variants can be empty if no test variants exist for this breakdown
            assert isinstance(breakdown_result.variants, list)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_mean_metric_with_winsorization_and_breakdown(self):
        """Test that winsorization computes per-breakdown percentiles, not global percentiles"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        # Use winsorization with p5 and p95 bounds
        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
            lower_bound_percentile=0.05,
            upper_bound_percentile=0.95,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - Chrome users have low values, Safari users have high values
        # This tests that percentiles are computed per-breakdown, not globally
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
                    # Chrome: values 10, 20; Safari: values 100, 200
                    # If percentiles were computed globally, Safari values would be capped at Chrome's p95
                    "amount": 10 + (i * 10) if browser == "Chrome" else 100 + (i - 2) * 100,
                    "$browser": browser,
                },
            )

        # Test group - similar pattern
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
                    "amount": 15 + (i * 10) if browser == "Chrome" else 110 + (i - 2) * 100,
                    "$browser": browser,
                },
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Verify breakdown structure exists

        assert result.breakdown_results is not None
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 2

        # Verify each breakdown has stats
        # The key validation is that Safari's high values aren't capped at Chrome's percentiles
        for breakdown_result in result.breakdown_results:
            assert breakdown_result.breakdown_value in [["Chrome"], ["Safari"]]
            assert breakdown_result.baseline is not None
            assert breakdown_result.variants is not None
            assert len(breakdown_result.variants) > 0

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_mean_metric_with_two_breakdowns(self):
        """Test mean metric calculations work correctly with 2 breakdown dimensions"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser"), Breakdown(property="$os")]),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - 8 users (2 per combination)
        for i in range(8):
            browser = "Chrome" if i < 4 else "Safari"
            os = "Windows" if i % 2 == 0 else "Mac"
            amount = {
                ("Chrome", "Windows"): 10,
                ("Chrome", "Mac"): 15,
                ("Safari", "Windows"): 20,
                ("Safari", "Mac"): 25,
            }[(browser, os)]

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
                    "$os": os,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: "control",
                    "amount": amount,
                    "$browser": browser,
                    "$os": os,
                },
            )

        # Test group - 8 users (2 per combination)
        for i in range(8):
            browser = "Chrome" if i < 4 else "Safari"
            os = "Windows" if i % 2 == 0 else "Mac"
            amount = {
                ("Chrome", "Windows"): 12,
                ("Chrome", "Mac"): 18,
                ("Safari", "Windows"): 22,
                ("Safari", "Mac"): 28,
            }[(browser, os)]

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
                    "$os": os,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: "test",
                    "amount": amount,
                    "$browser": browser,
                    "$os": os,
                },
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Basic structure
        assert result.baseline is not None
        assert result.variant_results is not None

        # Verify breakdown_results structure
        assert result.breakdown_results is not None
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 4

        # Verify each breakdown has correct structure
        for breakdown_result in result.breakdown_results:
            assert breakdown_result.baseline is not None
            assert breakdown_result.variants is not None
            assert len(breakdown_result.variants) > 0

            # Each variant has statistical data
            for variant in breakdown_result.variants:
                assert variant.key is not None
                assert variant.number_of_samples is not None
                assert variant.number_of_samples == 2  # 2 users per combination

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_mean_metric_with_three_breakdowns(self):
        """Test mean metric calculations work correctly with maximum (3) breakdown dimensions"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            breakdownFilter=BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$browser"),
                    Breakdown(property="$os"),
                    Breakdown(property="$device_type"),
                ]
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - 16 users (2 per combination for 8 combinations)
        for i in range(16):
            browser = "Chrome" if i < 8 else "Safari"
            os = "Windows" if i % 4 < 2 else "Mac"
            device_type = "Desktop" if i % 2 == 0 else "Mobile"
            amount = 10 + i  # Different amounts for variety

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
                    "$os": os,
                    "$device_type": device_type,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: "control",
                    "amount": amount,
                    "$browser": browser,
                    "$os": os,
                    "$device_type": device_type,
                },
            )

        # Test group - 16 users (2 per combination)
        for i in range(16):
            browser = "Chrome" if i < 8 else "Safari"
            os = "Windows" if i % 4 < 2 else "Mac"
            device_type = "Desktop" if i % 2 == 0 else "Mobile"
            amount = 12 + i  # Slightly higher amounts

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
                    "$os": os,
                    "$device_type": device_type,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: "test",
                    "amount": amount,
                    "$browser": browser,
                    "$os": os,
                    "$device_type": device_type,
                },
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Verify 8 breakdown combinations (2×2×2)
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 8

        # Spot check a specific breakdown
        chrome_windows_desktop = None
        assert result.breakdown_results is not None
        for breakdown_result in result.breakdown_results:
            if breakdown_result.breakdown_value == ["Chrome", "Windows", "Desktop"]:
                chrome_windows_desktop = breakdown_result
                break

        assert chrome_windows_desktop is not None
        assert chrome_windows_desktop is not None
        assert chrome_windows_desktop.baseline.number_of_samples == 2

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_two_breakdowns(self):
        """Test funnel metrics work with 2 breakdown dimensions"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentFunnelMetric(
            series=[EventsNode(event="purchase")],
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser"), Breakdown(property="$os")]),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - 12 users total (3 per combination)
        for i in range(12):
            browser = "Chrome" if i < 6 else "Safari"
            os = "Windows" if i % 6 < 3 else "Mac"
            # Vary completion: Chrome+Windows: 2/3, Chrome+Mac: 1/3, Safari+Windows: 3/3, Safari+Mac: 0/3
            completes_funnel = (
                (browser == "Chrome" and os == "Windows" and i % 3 < 2)
                or (browser == "Chrome" and os == "Mac" and i % 3 == 0)
                or (browser == "Safari" and os == "Windows")
            )

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
                    "$os": os,
                },
            )
            if completes_funnel:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: "control", "$browser": browser, "$os": os},
                )

        # Test group - inverse pattern
        for i in range(12):
            browser = "Chrome" if i < 6 else "Safari"
            os = "Windows" if i % 6 < 3 else "Mac"
            completes_funnel = (
                (browser == "Chrome" and os == "Windows" and i % 3 == 0)
                or (browser == "Chrome" and os == "Mac" and i % 3 < 2)
                or (browser == "Safari" and os == "Mac")
            )

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
                    "$os": os,
                },
            )
            if completes_funnel:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: "test", "$browser": browser, "$os": os},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 4

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_three_breakdowns(self):
        """Test funnel metrics work with 3 breakdown dimensions"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentFunnelMetric(
            series=[EventsNode(event="purchase")],
            breakdownFilter=BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$browser"),
                    Breakdown(property="$os"),
                    Breakdown(property="$device_type"),
                ]
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - 24 users (3 per combination for 8 combinations)
        for i in range(24):
            browser = "Chrome" if i < 12 else "Safari"
            os = "Windows" if i % 6 < 3 else "Mac"
            device_type = "Desktop" if i % 3 == 0 else "Mobile"
            completes_funnel = i % 2 == 0  # Half complete the funnel

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
                    "$os": os,
                    "$device_type": device_type,
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
                        "$os": os,
                        "$device_type": device_type,
                    },
                )

        # Test group - similar pattern
        for i in range(24):
            browser = "Chrome" if i < 12 else "Safari"
            os = "Windows" if i % 6 < 3 else "Mac"
            device_type = "Desktop" if i % 3 == 0 else "Mobile"
            completes_funnel = i % 2 == 1  # Different pattern

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
                    "$os": os,
                    "$device_type": device_type,
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
                        "$os": os,
                        "$device_type": device_type,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 8

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_ratio_metric_with_two_breakdowns(self):
        """Test ratio metrics work with 2 breakdown dimensions"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentRatioMetric(
            numerator=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
            denominator=EventsNode(event="view_item", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser"), Breakdown(property="$os")]),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - 8 users (2 per combination)
        for i in range(8):
            browser = "Chrome" if i < 4 else "Safari"
            os = "Windows" if i % 2 == 0 else "Mac"
            view_count = {
                ("Chrome", "Windows"): 2,
                ("Chrome", "Mac"): 3,
                ("Safari", "Windows"): 4,
                ("Safari", "Mac"): 5,
            }[(browser, os)]

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
                    "$os": os,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "control", "amount": 100, "$browser": browser, "$os": os},
            )
            for _ in range(view_count):
                _create_event(
                    team=self.team,
                    event="view_item",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T12:02:00Z",
                    properties={feature_flag_property: "control", "$browser": browser, "$os": os},
                )

        # Test group
        for i in range(8):
            browser = "Chrome" if i < 4 else "Safari"
            os = "Windows" if i % 2 == 0 else "Mac"
            view_count = {
                ("Chrome", "Windows"): 3,
                ("Chrome", "Mac"): 2,
                ("Safari", "Windows"): 5,
                ("Safari", "Mac"): 4,
            }[(browser, os)]

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
                    "$os": os,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "test", "amount": 150, "$browser": browser, "$os": os},
            )
            for _ in range(view_count):
                _create_event(
                    team=self.team,
                    event="view_item",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T12:02:00Z",
                    properties={feature_flag_property: "test", "$browser": browser, "$os": os},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 4

        # Verify ratio-specific fields exist
        for breakdown_result in result.breakdown_results:
            baseline = breakdown_result.baseline
            assert baseline.sum is not None
            assert baseline.denominator_sum is not None

            for variant in breakdown_result.variants:
                assert variant.sum is not None
                assert variant.denominator_sum is not None

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_ratio_metric_with_three_breakdowns(self):
        """Test ratio metrics work with 3 breakdown dimensions"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentRatioMetric(
            numerator=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
            denominator=EventsNode(event="view_item", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$browser"),
                    Breakdown(property="$os"),
                    Breakdown(property="$device_type"),
                ]
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - 16 users (2 per combination)
        for i in range(16):
            browser = "Chrome" if i < 8 else "Safari"
            os = "Windows" if i % 4 < 2 else "Mac"
            device_type = "Desktop" if i % 2 == 0 else "Mobile"
            view_count = 2 + (i % 4)  # Vary denominator

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
                    "$os": os,
                    "$device_type": device_type,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: "control",
                    "amount": 100,
                    "$browser": browser,
                    "$os": os,
                    "$device_type": device_type,
                },
            )
            for _ in range(view_count):
                _create_event(
                    team=self.team,
                    event="view_item",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T12:02:00Z",
                    properties={
                        feature_flag_property: "control",
                        "$browser": browser,
                        "$os": os,
                        "$device_type": device_type,
                    },
                )

        # Test group
        for i in range(16):
            browser = "Chrome" if i < 8 else "Safari"
            os = "Windows" if i % 4 < 2 else "Mac"
            device_type = "Desktop" if i % 2 == 0 else "Mobile"
            view_count = 3 + (i % 3)

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
                    "$os": os,
                    "$device_type": device_type,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: "test",
                    "amount": 150,
                    "$browser": browser,
                    "$os": os,
                    "$device_type": device_type,
                },
            )
            for _ in range(view_count):
                _create_event(
                    team=self.team,
                    event="view_item",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T12:02:00Z",
                    properties={
                        feature_flag_property: "test",
                        "$browser": browser,
                        "$os": os,
                        "$device_type": device_type,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 8

        # Verify 3-element breakdown values and ratio fields
        for breakdown_result in result.breakdown_results:
            assert len(breakdown_result.breakdown_value) == 3
            assert breakdown_result.baseline.sum is not None
            assert breakdown_result.baseline.denominator_sum is not None

    def test_breakdown_validation_raises_error_for_more_than_three(self):
        """Verify that using more than 3 breakdowns raises a ValidationError"""
        from pydantic import ValidationError as PydanticValidationError

        # Pydantic validates at schema level, so creating the BreakdownFilter should fail
        with pytest.raises(PydanticValidationError) as context:
            BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$browser"),
                    Breakdown(property="$os"),
                    Breakdown(property="$device_type"),
                    Breakdown(property="$country"),  # 4th breakdown - should fail
                ]
            )

        # Verify error message mentions too many items
        assert "at most 3 items" in str(context.value)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_missing_variants_across_breakdown_combinations(self):
        """Verify correct handling when control has all breakdown combinations but test is missing some"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser"), Breakdown(property="$os")]),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - ALL 4 combinations present
        for i in range(8):
            browser = "Chrome" if i < 4 else "Safari"
            os = "Windows" if i % 2 == 0 else "Mac"

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
                    "$os": os,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "control", "amount": 10, "$browser": browser, "$os": os},
            )

        # Test group - ONLY 2 combinations present (Chrome+Windows, Safari+Mac)
        for i in range(4):
            browser = "Chrome" if i < 2 else "Safari"
            os = "Windows" if i < 2 else "Mac"

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
                    "$os": os,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "test", "amount": 15, "$browser": browser, "$os": os},
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # All 4 breakdown combinations should still appear
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 4

        # Check that breakdown_results exist for all combinations
        chrome_mac_found = False
        safari_windows_found = False
        chrome_windows_found = False
        safari_mac_found = False

        for breakdown_result in result.breakdown_results:
            if breakdown_result.breakdown_value == ["Chrome", "Mac"]:
                chrome_mac_found = True
                # Control should have data
                assert breakdown_result.baseline is not None
                assert breakdown_result.baseline.number_of_samples == 2
                # Test variant may or may not be present for missing combinations

            if breakdown_result.breakdown_value == ["Safari", "Windows"]:
                safari_windows_found = True
                assert breakdown_result.baseline is not None
                assert breakdown_result.baseline.number_of_samples == 2

            if breakdown_result.breakdown_value == ["Chrome", "Windows"]:
                chrome_windows_found = True
                # This combination exists in both variants
                assert breakdown_result.baseline is not None
                assert breakdown_result.baseline.number_of_samples == 2
                assert len(breakdown_result.variants) > 0
                test_variant = breakdown_result.variants[0]
                assert test_variant.key == "test"
                assert test_variant.number_of_samples == 2

            if breakdown_result.breakdown_value == ["Safari", "Mac"]:
                safari_mac_found = True
                # This combination exists in both variants
                assert breakdown_result.baseline is not None
                assert breakdown_result.baseline.number_of_samples == 2
                assert len(breakdown_result.variants) > 0
                test_variant = breakdown_result.variants[0]
                assert test_variant.key == "test"
                assert test_variant.number_of_samples == 2

        assert chrome_mac_found, "Chrome+Mac breakdown should exist"
        assert safari_windows_found, "Safari+Windows breakdown should exist"
        assert chrome_windows_found, "Chrome+Windows breakdown should exist"
        assert safari_mac_found, "Safari+Mac breakdown should exist"

    @skip("potential flakiness")
    @freeze_time("2023-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_data_warehouse_mean_metric_with_breakdown(self):
        """Test data warehouse mean metrics work with breakdowns"""
        table_name = self.create_data_warehouse_table_with_usage()
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2023, 1, 1), end_date=datetime(2023, 1, 31)
        )
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=ExperimentDataWarehouseNode(
                table_name=table_name,
                events_join_key="properties.$user_id",
                data_warehouse_join_key="userid",
                timestamp_field="ds",
                math=ExperimentMetricMathType.SUM,
                math_property="usage",
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="plan")]),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group: 6 users
        for i in range(6):
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"distinct_control_{i}",
                properties={
                    "$feature_flag_response": "control",
                    feature_flag_property: "control",
                    "$feature_flag": feature_flag.key,
                    "$user_id": f"user_control_{i}",
                },
                timestamp=datetime(2023, 1, i + 1),
            )

        # Test group: 6 users
        for i in range(6):
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"distinct_test_{i}",
                properties={
                    "$feature_flag_response": "test",
                    feature_flag_property: "test",
                    "$feature_flag": feature_flag.key,
                    "$user_id": f"user_test_{i}",
                },
                timestamp=datetime(2023, 1, i + 1),
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Verify breakdown by data warehouse property

        # Verify breakdown_results structure
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) > 0

        for breakdown_result in result.breakdown_results:
            assert breakdown_result.baseline is not None
            assert len(breakdown_result.variants) > 0

    @skip("potential flakiness")
    @freeze_time("2023-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_data_warehouse_ratio_metric_with_breakdown(self):
        """Test data warehouse ratio metrics work with breakdowns"""
        usage_table = self.create_data_warehouse_table_with_usage()
        subscriptions_table = self.create_data_warehouse_table_with_subscriptions()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2023, 1, 1), end_date=datetime(2023, 1, 31)
        )
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        metric = ExperimentRatioMetric(
            numerator=ExperimentDataWarehouseNode(
                table_name=usage_table,
                events_join_key="properties.$user_id",
                data_warehouse_join_key="userid",
                timestamp_field="ds",
                math=ExperimentMetricMathType.SUM,
                math_property="usage",
            ),
            denominator=ExperimentDataWarehouseNode(
                table_name=subscriptions_table,
                events_join_key="person.properties.email",
                data_warehouse_join_key="subscription_customer.customer_email",
                timestamp_field="subscription_created_at",
                math=ExperimentMetricMathType.TOTAL,
            ),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="region")]),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group
        for i in range(3):
            _create_person(
                team=self.team, distinct_ids=[f"user_control_{i}"], properties={"email": f"user{i}@example.com"}
            )
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                properties={
                    "$feature_flag_response": "control",
                    feature_flag_property: "control",
                    "$feature_flag": feature_flag.key,
                    "$user_id": f"user_control_{i}",
                },
                timestamp=datetime(2023, 1, i + 1),
            )

        # Test group
        for i in range(3):
            _create_person(
                team=self.team, distinct_ids=[f"user_test_{i}"], properties={"email": f"test{i}@example.com"}
            )
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                properties={
                    "$feature_flag_response": "test",
                    feature_flag_property: "test",
                    "$feature_flag": feature_flag.key,
                    "$user_id": f"user_test_{i}",
                },
                timestamp=datetime(2023, 1, i + 1),
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        # Verify breakdown structure

        # Verify ratio-specific fields per breakdown
        assert result.breakdown_results is not None
        for breakdown_result in result.breakdown_results:
            baseline = breakdown_result.baseline
            assert baseline.sum is not None
            assert baseline.denominator_sum is not None

            for variant in breakdown_result.variants:
                assert variant.sum is not None
                assert variant.denominator_sum is not None

    @parameterized.expand([("new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_retention_metric_with_breakdown(self, name, use_new_query_builder):
        """
        Test retention metric with single breakdown dimension.

        Retention = (users who completed) / (users who started)
        Breakdown by $browser (Chrome/Safari)
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        metric = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="signup",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="login",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
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

        # Control group - different retention rates per browser
        # Chrome: 2 users, 2 sign up, 2 return (100% retention)
        # Safari: 2 users, 2 sign up, 1 returns (50% retention)
        for i in range(4):
            browser = "Chrome" if i < 2 else "Safari"
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)

            # Exposure event with breakdown property
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

            # All users sign up (start event)
            _create_event(
                team=self.team,
                event="signup",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "control"},
            )

            # Chrome users all return, Safari only first one returns
            if i < 2 or i == 2:
                _create_event(
                    team=self.team,
                    event="login",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-05T12:00:00Z",  # Day 3 after signup
                    properties={feature_flag_property: "control"},
                )

        # Test group
        # Chrome: 2 users, 2 sign up, 1 returns (50% retention)
        # Safari: 2 users, 2 sign up, 2 return (100% retention)
        for i in range(4):
            browser = "Chrome" if i < 2 else "Safari"
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)

            # Exposure event with breakdown property
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

            # All users sign up (start event)
            _create_event(
                team=self.team,
                event="signup",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "test"},
            )

            # Safari users all return, Chrome only first one returns
            if i >= 2 or i == 0:
                _create_event(
                    team=self.team,
                    event="login",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-05T12:00:00Z",  # Day 3 after signup
                    properties={feature_flag_property: "test"},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None

        # Verify breakdown_results is populated with per-breakdown statistics
        assert result.breakdown_results is not None
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 2

        # Verify each breakdown has correct structure (breakdown_value is a list)
        for breakdown_result in result.breakdown_results:
            assert breakdown_result.breakdown_value in [["Chrome"], ["Safari"]]
            assert breakdown_result.baseline is not None
            assert breakdown_result.variants is not None
            assert len(breakdown_result.variants) > 0

            baseline = breakdown_result.baseline
            assert baseline.number_of_samples is not None
            assert baseline.sum is not None

            for variant in breakdown_result.variants:
                assert variant.number_of_samples is not None
                assert variant.sum is not None

    @parameterized.expand([("new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_retention_metric_with_two_breakdowns(self, name, use_new_query_builder):
        """
        Test retention metric with two breakdown dimensions.

        Breakdown by $browser × $os
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        metric = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="signup",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="login",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser"), Breakdown(property="$os")]),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group - 4 breakdown combinations: Chrome×Mac, Chrome×Windows, Safari×Mac, Safari×Windows
        for i in range(8):
            browser = "Chrome" if i < 4 else "Safari"
            os = "Mac" if i % 2 == 0 else "Windows"
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)

            # Exposure event with breakdown properties
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
                    "$os": os,
                },
            )

            # All users sign up
            _create_event(
                team=self.team,
                event="signup",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "control"},
            )

            # First user of each combination returns (50% retention per combination)
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="login",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-05T12:00:00Z",
                    properties={feature_flag_property: "control"},
                )

        # Test group
        for i in range(8):
            browser = "Chrome" if i < 4 else "Safari"
            os = "Mac" if i % 2 == 0 else "Windows"
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)

            # Exposure event with breakdown properties
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
                    "$os": os,
                },
            )

            # All users sign up
            _create_event(
                team=self.team,
                event="signup",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "test"},
            )

            # All users return (100% retention)
            _create_event(
                team=self.team,
                event="login",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-05T12:00:00Z",
                properties={feature_flag_property: "test"},
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None

        # Verify breakdown_results has all 4 combinations
        assert result.breakdown_results is not None
        assert result.breakdown_results is not None
        assert len(result.breakdown_results) == 4

        # Verify each breakdown has correct structure (breakdown_value is a list of 2 elements)
        breakdown_values = [br.breakdown_value for br in result.breakdown_results]
        expected_combinations = [
            ["Chrome", "Mac"],
            ["Chrome", "Windows"],
            ["Safari", "Mac"],
            ["Safari", "Windows"],
        ]
        for expected in expected_combinations:
            assert expected in breakdown_values

        for breakdown_result in result.breakdown_results:
            assert breakdown_result.baseline is not None
            assert breakdown_result.variants is not None
            assert len(breakdown_result.variants) > 0
