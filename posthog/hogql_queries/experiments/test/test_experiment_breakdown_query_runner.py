from datetime import datetime

from django.test import override_settings
from freezegun import freeze_time

from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.experiments.experiment_breakdown_query_runner import ExperimentBreakdownQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from posthog.schema import ExperimentBreakdownQuery, ExperimentFunnelMetric, EventsNode
from posthog.test.base import (
    snapshot_clickhouse_queries,
)
from posthog.test.test_journeys import journeys_for


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentBreakdownQueryRunner(ExperimentQueryRunnerBaseTest):
    def setUp(self):
        super().setUp()
        self.feature_flag = self.create_feature_flag()
        # Use naive datetimes - the base class will make them timezone-aware
        self.experiment = self.create_experiment(
            feature_flag=self.feature_flag,
            start_date=datetime(2024, 1, 1),  # Remove timezone info
            end_date=datetime(2024, 1, 7),  # Remove timezone info
        )

    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_breakdown_query_returns_correct_variants(self):
        """
        Test that the breakdown query returns results for each variant including $multiple
        """
        ff_property = f"$feature/{self.feature_flag.key}"

        # Create test data with users exposed to different variants
        journeys_for(
            {
                "user_control_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02 12:01:00",  # Fixed timestamp format
                        "properties": {"amount": 10, "country": "US"},
                    },
                ],
                "user_control_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02 12:01:00",  # Fixed timestamp format
                        "properties": {"amount": 20, "country": "UK"},
                    },
                ],
                "user_test_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02 12:01:00",  # Fixed timestamp format
                        "properties": {"amount": 15, "country": "US"},
                    },
                ],
                "user_test_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02 12:01:00",  # Fixed timestamp format
                        "properties": {"amount": 25, "country": "CA"},
                    },
                ],
                "user_multiple_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03 12:01:00",  # Fixed timestamp format
                        "properties": {"amount": 30, "country": "US"},
                    },
                ],
            },
            self.team,
        )

        # Create the query - using the same breakdown configuration as resultsBreakdownLogic
        query = ExperimentBreakdownQuery(
            kind="ExperimentBreakdownQuery",
            experiment_id=self.experiment.id,
            metric=ExperimentFunnelMetric(
                metric_type="funnel",
                series=[EventsNode(event="purchase")],
            ),
        )

        # Execute the query
        runner = ExperimentBreakdownQueryRunner(
            query=query,
            team=self.team,
        )
        result = runner.calculate()

        # Assert the response structure
        self.assertEqual(result.kind, "ExperimentBreakdownQuery")
        self.assertEqual(result.experiment_id, self.experiment.id)
        self.assertIn("control", result.variants)
        self.assertIn("test", result.variants)
        self.assertIn(MULTIPLE_VARIANT_KEY, result.variants)

        # Assert we have breakdown results
        self.assertIsInstance(result.results, list)
        self.assertGreater(len(result.results), 0)

        # Check that we have results for each variant
        variant_results = {}
        for item in result.results:
            variant = item["variant"]
            if variant not in variant_results:
                variant_results[variant] = []
            variant_results[variant].append(item)

        # Should have results for control, test, and $multiple variants
        self.assertIn("control", variant_results)
        self.assertIn("test", variant_results)
        self.assertIn(MULTIPLE_VARIANT_KEY, variant_results)

        # Check that breakdown values are present
        for _variant, results in variant_results.items():
            self.assertGreater(len(results), 0)
            for item in results:
                self.assertIn("breakdown_value", item)
                self.assertIn("count", item)
                self.assertIn("unique_users", item)
                self.assertIsInstance(item["count"], int)
                self.assertIsInstance(item["unique_users"], int)

        # Verify that the breakdown values match the variants
        breakdown_values = {item["breakdown_value"] for item in result.results}
        expected_values = {"control", "test", MULTIPLE_VARIANT_KEY}
        self.assertEqual(breakdown_values, expected_values)
