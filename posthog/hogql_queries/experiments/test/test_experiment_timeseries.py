from datetime import datetime
from typing import Any, cast
from freezegun import freeze_time

from posthog.hogql_queries.experiments.experiment_timeseries import ExperimentTimeseries
from posthog.models import Experiment, FeatureFlag
from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
    ExperimentFunnelMetric,
)
from posthog.test.base import (
    BaseTest,
    _create_event,
    _create_person,
    flush_persons_and_events,
)


class TestExperimentTimeseries(BaseTest):
    @staticmethod
    def get_test_data():
        """Test data used for both mean and funnel metric tests"""
        return [
            {
                "date": "2024-01-01",
                "control": {"exposed_users": 10, "converting_users": 8},
                "test": {"exposed_users": 10, "converting_users": 9},
            },
            {
                "date": "2024-01-02",
                "control": {"exposed_users": 20, "converting_users": 16},
                "test": {"exposed_users": 20, "converting_users": 17},
            },
            {
                "date": "2024-01-03",
                "control": {"exposed_users": 30, "converting_users": 24},
                "test": {"exposed_users": 30, "converting_users": 26},
            },
            {
                "date": "2024-01-04",
                "control": {"exposed_users": 40, "converting_users": 32},
                "test": {"exposed_users": 40, "converting_users": 34},
            },
            {
                "date": "2024-01-05",
                "control": {"exposed_users": 50, "converting_users": 40},
                "test": {"exposed_users": 50, "converting_users": 43},
            },
        ]

    @staticmethod
    def get_expected_cumulative_values(test_data, up_to_day_index, variant):
        """Calculate cumulative exposed users and conversions up to a given day"""
        cumulative_exposed = sum(day[variant]["exposed_users"] for day in test_data[: up_to_day_index + 1])
        cumulative_conversions = sum(day[variant]["converting_users"] for day in test_data[: up_to_day_index + 1])
        return cumulative_exposed, cumulative_conversions

    @freeze_time("2024-01-01T12:00:00Z")
    def test_basic_timeseries_query_mean_metric(self):
        """Test basic timeseries functionality with a mean metric and a 5-day experiment"""

        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            key="test_flag",
            name="Test Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        # 5-day time range
        experiment = Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 6),
        )

        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview"),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        test_data = self.get_test_data()

        for day_data in test_data:
            date = day_data["date"]

            for variant in ["control", "test"]:
                variant_data = day_data[variant]
                exposed_users = variant_data["exposed_users"]
                converting_users = variant_data["converting_users"]

                for i in range(exposed_users):
                    user_id = f"user_{variant}_{date}_{i}"
                    _create_person(distinct_ids=[user_id], team_id=self.team.pk)

                    _create_event(
                        team=self.team,
                        event="$feature_flag_called",
                        distinct_id=user_id,
                        timestamp=f"{date}T10:00:00Z",
                        properties={
                            feature_flag_property: variant,
                            "$feature_flag_response": variant,
                            "$feature_flag": feature_flag.key,
                        },
                    )

                    if i < converting_users:
                        _create_event(
                            team=self.team,
                            event="$pageview",
                            distinct_id=user_id,
                            timestamp=f"{date}T11:00:00Z",
                            properties={feature_flag_property: variant},
                        )

        flush_persons_and_events()

        timeseries = ExperimentTimeseries(experiment, metric)
        results = timeseries.get_result()

        expected_results = [
            {
                "date": "2024-01-01",
                "baseline": {
                    "key": "control",
                    "number_of_samples": 10,
                    "sum": 8.0,
                    "sum_squares": 8.0,
                },
                "variant_results": [
                    {
                        "key": "test",
                        "number_of_samples": 10,
                        "sum": 9.0,
                        "sum_squares": 9.0,
                        "significant": None,
                        "credible_interval": None,
                        "chance_to_win": None,
                    }
                ],
            },
            {
                "date": "2024-01-02",
                "baseline": {
                    "key": "control",
                    "number_of_samples": 30,
                    "sum": 24.0,
                    "sum_squares": 24.0,
                },
                "variant_results": [
                    {
                        "key": "test",
                        "number_of_samples": 30,
                        "sum": 26.0,
                        "sum_squares": 26.0,
                        "significant": None,
                        "credible_interval": None,
                        "chance_to_win": None,
                    }
                ],
            },
            {
                "date": "2024-01-03",
                "baseline": {
                    "key": "control",
                    "number_of_samples": 60,
                    "sum": 48.0,
                    "sum_squares": 48.0,
                },
                "variant_results": [
                    {
                        "key": "test",
                        "number_of_samples": 60,
                        "sum": 52.0,
                        "sum_squares": 52.0,
                        "significant": False,
                        "credible_interval": [-0.092334468537072, 0.25900113520373863],
                        "chance_to_win": 0.8237544370302499,
                    }
                ],
            },
            {
                "date": "2024-01-04",
                "baseline": {
                    "key": "control",
                    "number_of_samples": 100,
                    "sum": 80.0,
                    "sum_squares": 80.0,
                },
                "variant_results": [
                    {
                        "key": "test",
                        "number_of_samples": 100,
                        "sum": 86.0,
                        "sum_squares": 86.0,
                        "significant": False,
                        "credible_interval": [-0.06105167998544181, 0.21105167998544166],
                        "chance_to_win": 0.8600295068945255,
                    }
                ],
            },
            {
                "date": "2024-01-05",
                "baseline": {
                    "key": "control",
                    "number_of_samples": 150,
                    "sum": 120.0,
                    "sum_squares": 120.0,
                },
                "variant_results": [
                    {
                        "key": "test",
                        "number_of_samples": 150,
                        "sum": 129.0,
                        "sum_squares": 129.0,
                        "significant": False,
                        "credible_interval": [-0.03589918945544256, 0.18589918945544243],
                        "chance_to_win": 0.9074979477365419,
                    }
                ],
            },
            {"date": "2024-01-06"},
        ]

        self.assertEqual(len(results), len(expected_results))

        for _, (_actual_result, _expected_result) in enumerate(zip(results, expected_results)):
            actual_result = cast(dict[str, Any], _actual_result)
            expected_result = cast(dict[str, Any], _expected_result)
            self.assertTrue(actual_result["date"].startswith(expected_result["date"]))

            # Check if this expected result has data or is just a date-only bucket
            if "baseline" in expected_result:
                self.assertIn("baseline", actual_result)
                actual_baseline = actual_result["baseline"]
                expected_baseline = expected_result["baseline"]

                self.assertEqual(actual_baseline["key"], expected_baseline["key"])
                self.assertEqual(actual_baseline["number_of_samples"], expected_baseline["number_of_samples"])
                self.assertEqual(actual_baseline["sum"], expected_baseline["sum"])
                self.assertEqual(actual_baseline["sum_squares"], expected_baseline["sum_squares"])

                self.assertIn("variant_results", actual_result)
                self.assertEqual(len(actual_result["variant_results"]), 1)

                actual_test_variant = actual_result["variant_results"][0]
                expected_test_variant = expected_result["variant_results"][0]

                self.assertEqual(actual_test_variant["key"], expected_test_variant["key"])
                self.assertEqual(actual_test_variant["number_of_samples"], expected_test_variant["number_of_samples"])
                self.assertEqual(actual_test_variant["sum"], expected_test_variant["sum"])
                self.assertEqual(actual_test_variant["sum_squares"], expected_test_variant["sum_squares"])

                self.assertEqual(actual_test_variant["significant"], expected_test_variant["significant"])

                if expected_test_variant["credible_interval"] is not None:
                    self.assertIsNotNone(actual_test_variant["credible_interval"])
                    for actual_val, expected_val in zip(
                        actual_test_variant["credible_interval"], expected_test_variant["credible_interval"]
                    ):
                        self.assertAlmostEqual(actual_val, expected_val, places=4)
                else:
                    self.assertIsNone(actual_test_variant["credible_interval"])

                if expected_test_variant["chance_to_win"] is not None:
                    self.assertIsNotNone(actual_test_variant["chance_to_win"])
                    self.assertAlmostEqual(
                        actual_test_variant["chance_to_win"], expected_test_variant["chance_to_win"], places=4
                    )
                else:
                    self.assertIsNone(actual_test_variant["chance_to_win"])
            else:
                # For date-only buckets, ensure they only have the date field
                self.assertEqual(len(actual_result), 1)
                self.assertIn("date", actual_result)

    @freeze_time("2024-01-01T12:00:00Z")
    def test_basic_timeseries_query_funnel_metric(self):
        """Test basic timeseries functionality with a funnel metric and a 5-day experiment"""

        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            key="test_flag",
            name="Test Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        # 5-day time range
        experiment = Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 6),
        )

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="purchase"),
            ],
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        test_data = self.get_test_data()

        for day_data in test_data:
            date = day_data["date"]

            for variant in ["control", "test"]:
                variant_data = day_data[variant]
                exposed_users = variant_data["exposed_users"]
                converting_users = variant_data["converting_users"]

                for i in range(exposed_users):
                    user_id = f"user_{variant}_{date}_{i}"
                    _create_person(distinct_ids=[user_id], team_id=self.team.pk)

                    _create_event(
                        team=self.team,
                        event="$feature_flag_called",
                        distinct_id=user_id,
                        timestamp=f"{date}T10:00:00Z",
                        properties={
                            feature_flag_property: variant,
                            "$feature_flag_response": variant,
                            "$feature_flag": feature_flag.key,
                        },
                    )

                    if i < converting_users:
                        _create_event(
                            team=self.team,
                            event="purchase",
                            distinct_id=user_id,
                            timestamp=f"{date}T11:00:00Z",
                            properties={feature_flag_property: variant},
                        )

        flush_persons_and_events()

        timeseries = ExperimentTimeseries(experiment, metric)
        results = timeseries.get_result()

        # Expected statistical results for the 5-day test data
        expected_results = [
            {
                "date": "2024-01-01",
                "baseline": {
                    "key": "control",
                    "number_of_samples": 10,
                    "sum": 8.0,
                    "sum_squares": 8.0,
                    "validation_failures": ["not-enough-exposures"],
                },
                "variant_results": [
                    {
                        "chance_to_win": None,
                        "credible_interval": None,
                        "key": "test",
                        "number_of_samples": 10,
                        "significant": None,
                        "sum": 9.0,
                        "sum_squares": 9.0,
                        "validation_failures": ["not-enough-exposures"],
                    }
                ],
            },
            {
                "date": "2024-01-02",
                "baseline": {
                    "key": "control",
                    "number_of_samples": 30,
                    "sum": 24.0,
                    "sum_squares": 24.0,
                    "validation_failures": ["not-enough-exposures"],
                },
                "variant_results": [
                    {
                        "chance_to_win": None,
                        "credible_interval": None,
                        "key": "test",
                        "number_of_samples": 30,
                        "significant": None,
                        "sum": 26.0,
                        "sum_squares": 26.0,
                        "validation_failures": ["not-enough-exposures"],
                    }
                ],
            },
            {
                "date": "2024-01-03",
                "baseline": {
                    "key": "control",
                    "number_of_samples": 60,
                    "sum": 48.0,
                    "sum_squares": 48.0,
                    "validation_failures": [],
                },
                "variant_results": [
                    {
                        "chance_to_win": 0.8257787117026323,
                        "credible_interval": [-0.09086441924616176, 0.25753108591282836],
                        "key": "test",
                        "number_of_samples": 60,
                        "significant": False,
                        "sum": 52.0,
                        "sum_squares": 52.0,
                        "validation_failures": [],
                    }
                ],
            },
            {
                "date": "2024-01-04",
                "baseline": {
                    "key": "control",
                    "number_of_samples": 100,
                    "sum": 80.0,
                    "sum_squares": 80.0,
                    "validation_failures": [],
                },
                "variant_results": [
                    {
                        "chance_to_win": 0.8612372835495565,
                        "credible_interval": [-0.060369712382764756, 0.2103697123827646],
                        "key": "test",
                        "number_of_samples": 100,
                        "significant": False,
                        "sum": 86.0,
                        "sum_squares": 86.0,
                        "validation_failures": [],
                    }
                ],
            },
            {
                "date": "2024-01-05",
                "baseline": {
                    "key": "control",
                    "number_of_samples": 150,
                    "sum": 120.0,
                    "sum_squares": 120.0,
                    "validation_failures": [],
                },
                "variant_results": [
                    {
                        "chance_to_win": 0.9082317007711804,
                        "credible_interval": [-0.03552890732169711, 0.18552890732169697],
                        "key": "test",
                        "number_of_samples": 150,
                        "significant": False,
                        "sum": 129.0,
                        "sum_squares": 129.0,
                        "validation_failures": [],
                    }
                ],
            },
            {"date": "2024-01-06"},
        ]

        self.assertEqual(len(results), len(expected_results))

        for _, (_actual_result, _expected_result) in enumerate(zip(results, expected_results)):
            actual_result = cast(dict[str, Any], _actual_result)
            expected_result = cast(dict[str, Any], _expected_result)
            self.assertTrue(actual_result["date"].startswith(expected_result["date"]))

            # Check if this expected result has data or is just a date-only bucket
            if "baseline" in expected_result:
                self.assertIn("baseline", actual_result)
                actual_baseline = actual_result["baseline"]
                expected_baseline = expected_result["baseline"]

                self.assertEqual(actual_baseline["key"], expected_baseline["key"])
                self.assertEqual(actual_baseline["number_of_samples"], expected_baseline["number_of_samples"])
                self.assertEqual(actual_baseline["sum"], expected_baseline["sum"])
                self.assertEqual(actual_baseline["sum_squares"], expected_baseline["sum_squares"])
                self.assertEqual(actual_baseline["validation_failures"], expected_baseline["validation_failures"])

                self.assertIn("variant_results", actual_result)
                self.assertEqual(len(actual_result["variant_results"]), 1)

                actual_test_variant = actual_result["variant_results"][0]
                expected_test_variant = expected_result["variant_results"][0]

                self.assertEqual(actual_test_variant["key"], expected_test_variant["key"])
                self.assertEqual(actual_test_variant["number_of_samples"], expected_test_variant["number_of_samples"])
                self.assertEqual(actual_test_variant["sum"], expected_test_variant["sum"])
                self.assertEqual(actual_test_variant["sum_squares"], expected_test_variant["sum_squares"])
                self.assertEqual(
                    actual_test_variant["validation_failures"], expected_test_variant["validation_failures"]
                )

                self.assertEqual(actual_test_variant["significant"], expected_test_variant["significant"])

                if expected_test_variant["credible_interval"] is not None:
                    self.assertIsNotNone(actual_test_variant["credible_interval"])
                    for actual_val, expected_val in zip(
                        actual_test_variant["credible_interval"], expected_test_variant["credible_interval"]
                    ):
                        self.assertAlmostEqual(actual_val, expected_val, places=4)
                else:
                    self.assertIsNone(actual_test_variant["credible_interval"])

                if expected_test_variant["chance_to_win"] is not None:
                    self.assertIsNotNone(actual_test_variant["chance_to_win"])
                    self.assertAlmostEqual(
                        actual_test_variant["chance_to_win"], expected_test_variant["chance_to_win"], places=4
                    )
                else:
                    self.assertIsNone(actual_test_variant["chance_to_win"])
            else:
                # For date-only buckets, ensure they only have the date field
                self.assertEqual(len(actual_result), 1)
                self.assertIn("date", actual_result)
