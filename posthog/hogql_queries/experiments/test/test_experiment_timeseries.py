from datetime import datetime
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

        self.assertEqual(len(results), len(test_data))

        for day_index, (day_result, expected_day) in enumerate(zip(results, test_data)):
            self.assertTrue(day_result["date"].startswith(expected_day["date"]))
            self.assertEqual(len(day_result["variant_results"]), 2)  # control and test

            variants = {v["key"]: v for v in day_result["variant_results"]}
            self.assertIn("control", variants)
            self.assertIn("test", variants)

            for variant in ["control", "test"]:
                expected_users, expected_conversions = self.get_expected_cumulative_values(
                    test_data, day_index, variant
                )
                actual_users = variants[variant]["number_of_samples"]
                actual_conversions = variants[variant]["sum"]

                self.assertEqual(
                    actual_users,
                    expected_users,
                    f"Day {day_index + 1} {variant}: expected {expected_users} users, got {actual_users}",
                )

                self.assertEqual(
                    actual_conversions,
                    expected_conversions,
                    f"Day {day_index + 1} {variant}: expected {expected_conversions} conversions, got {actual_conversions}",
                )

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

        self.assertEqual(len(results), len(test_data))

        for day_index, (day_result, expected_day) in enumerate(zip(results, test_data)):
            self.assertTrue(day_result["date"].startswith(expected_day["date"]))
            self.assertEqual(len(day_result["variant_results"]), 2)  # control and test

            variants = {v["key"]: v for v in day_result["variant_results"]}
            self.assertIn("control", variants)
            self.assertIn("test", variants)

            for variant in ["control", "test"]:
                expected_users, expected_conversions = self.get_expected_cumulative_values(
                    test_data, day_index, variant
                )
                actual_users = variants[variant]["number_of_samples"]
                actual_conversions = variants[variant]["sum"]

                self.assertEqual(
                    actual_users,
                    expected_users,
                    f"Day {day_index + 1} {variant}: expected {expected_users} users, got {actual_users}",
                )

                self.assertEqual(
                    actual_conversions,
                    expected_conversions,
                    f"Day {day_index + 1} {variant}: expected {expected_conversions} conversions, got {actual_conversions}",
                )
