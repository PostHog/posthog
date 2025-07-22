from datetime import datetime
from typing import Any
from freezegun import freeze_time

from posthog.hogql_queries.experiments.experiment_timeseries import ExperimentTimeseries
from posthog.models import Experiment, FeatureFlag
from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
)
from posthog.test.base import (
    BaseTest,
    _create_event,
    _create_person,
    flush_persons_and_events,
)


class TestExperimentTimeseries(BaseTest):
    @freeze_time("2024-01-01T12:00:00Z")
    def test_basic_timeseries_query(self):
        """Test basic timeseries functionality with a 5-day experiment"""

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

        # Create experiment with 5-day time range
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
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        test_data: list[dict[str, Any]] = [
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

        def get_expected_cumulative_values(test_data, up_to_day_index, variant):
            """Calculate cumulative exposed users and conversions up to a given day"""
            cumulative_exposed = sum(day[variant]["exposed_users"] for day in test_data[: up_to_day_index + 1])
            cumulative_conversions = sum(day[variant]["converting_users"] for day in test_data[: up_to_day_index + 1])
            return cumulative_exposed, cumulative_conversions

        timeseries = ExperimentTimeseries(experiment)
        results = timeseries.get_result()

        self.assertEqual(len(results), len(test_data))  # Same number of days as test data

        for day_index, (day_result, expected_day) in enumerate(zip(results, test_data)):
            self.assertTrue(day_result["date"].startswith(expected_day["date"]))
            self.assertEqual(len(day_result["variant_results"]), 2)  # control and test

            variants = {v["key"]: v for v in day_result["variant_results"]}
            self.assertIn("control", variants)
            self.assertIn("test", variants)

            for variant in ["control", "test"]:
                expected_users, _ = get_expected_cumulative_values(test_data, day_index, variant)
                actual_users = variants[variant]["number_of_samples"]

                self.assertEqual(
                    actual_users,
                    expected_users,
                    f"Day {day_index + 1} {variant}: expected {expected_users} users, got {actual_users}",
                )

                self.assertGreater(
                    variants[variant]["sum"], 0, f"Day {day_index + 1} {variant}: should have positive conversions"
                )

        day1_variants = {v["key"]: v for v in results[0]["variant_results"]}
        day5_variants = {v["key"]: v for v in results[4]["variant_results"]}

        self.assertEqual(day1_variants["control"]["number_of_samples"], 10)
        self.assertEqual(day1_variants["test"]["number_of_samples"], 10)

        self.assertEqual(day5_variants["control"]["number_of_samples"], 150)
        self.assertEqual(day5_variants["test"]["number_of_samples"], 150)

        self.assertGreater(day5_variants["test"]["sum"], day5_variants["control"]["sum"])

        for day_index in range(1, len(results)):
            current_variants = {v["key"]: v for v in results[day_index]["variant_results"]}
            previous_variants = {v["key"]: v for v in results[day_index - 1]["variant_results"]}

            for variant in ["control", "test"]:
                self.assertGreater(
                    current_variants[variant]["number_of_samples"],
                    previous_variants[variant]["number_of_samples"],
                    f"Day {day_index + 1} {variant} users should be > Day {day_index} users (cumulative)",
                )
                self.assertGreaterEqual(
                    current_variants[variant]["sum"],
                    previous_variants[variant]["sum"],
                    f"Day {day_index + 1} {variant} sum should be >= Day {day_index} sum (cumulative)",
                )
