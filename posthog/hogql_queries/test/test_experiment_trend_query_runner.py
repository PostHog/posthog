from django.test import override_settings
from posthog.hogql_queries.experiment_trend_query_runner import ExperimentTrendQueryRunner
from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.schema import (
    EventsNode,
    ExperimentTrendQuery,
    ExperimentTrendQueryResponse,
    TrendsQuery,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from freezegun import freeze_time
from typing import cast
from django.utils import timezone
from datetime import timedelta
from posthog.test.test_journeys import journeys_for


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentTrendQueryRunner(ClickhouseTestMixin, APIBaseTest):
    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner(self):
        feature_flag = FeatureFlag.objects.create(
            name="Test experiment flag",
            key="test-experiment",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "test",
                            "name": "Test",
                            "rollout_percentage": 50,
                        },
                    ]
                },
            },
            created_by=self.user,
        )
        experiment = Experiment.objects.create(
            name="test-experiment",
            team=self.team,
            feature_flag=feature_flag,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=14),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        # Populate experiment events
        for variant, count in [("control", 11), ("test", 15)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    properties={feature_flag_property: variant},
                )

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    properties={feature_flag_property: variant},
                )

        flush_persons_and_events()

        query_runner = ExperimentTrendQueryRunner(
            query=ExperimentTrendQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        self.assertEqual(result.insight, "TRENDS")
        self.assertEqual(len(result.results), 2)

        trend_result = cast(ExperimentTrendQueryResponse, result)

        self.assertIn("control", trend_result.results)
        self.assertIn("test", trend_result.results)

        control_result = trend_result.results["control"]
        test_result = trend_result.results["test"]

        self.assertEqual(control_result.count, 11)
        self.assertEqual(test_result.count, 15)

        self.assertEqual(control_result.exposure, 7)
        self.assertEqual(test_result.exposure, 9)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_custom_exposure(self):
        feature_flag = FeatureFlag.objects.create(
            name="Test experiment flag",
            key="test-experiment",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "test",
                            "name": "Test",
                            "rollout_percentage": 50,
                        },
                    ]
                },
            },
            created_by=self.user,
        )
        experiment = Experiment.objects.create(
            name="test-experiment",
            team=self.team,
            feature_flag=feature_flag,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=14),
        )

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        exposure_query = TrendsQuery(
            series=[EventsNode(event="custom_exposure_event", properties=[{"key": "valid_exposure", "value": "true"}])]
        )

        experiment_query = ExperimentTrendQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "valid_exposure": "true"},
                    },
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "valid_exposure": "true"},
                    },
                ],
                "user_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02"},
                ],
                "user_out_of_control_exposure": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "false"},
                    },
                ],
                "user_out_of_date_range": [
                    {"event": "$pageview", "timestamp": "2019-01-01", "properties": {ff_property: "control"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2019-01-01",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendQueryRunner(
            query=ExperimentTrendQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendQueryResponse, result)

        self.assertIn("control", trend_result.results)
        self.assertIn("test", trend_result.results)

        control_result = trend_result.results["control"]
        test_result = trend_result.results["test"]

        self.assertEqual(control_result.count, 3)
        self.assertEqual(test_result.count, 5)

        self.assertEqual(control_result.exposure, 2)
        self.assertEqual(test_result.exposure, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_default_exposure(self):
        feature_flag = FeatureFlag.objects.create(
            name="Test experiment flag",
            key="test-experiment",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "test",
                            "name": "Test",
                            "rollout_percentage": 50,
                        },
                    ]
                },
            },
            created_by=self.user,
        )
        experiment = Experiment.objects.create(
            name="test-experiment",
            team=self.team,
            feature_flag=feature_flag,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=14),
        )

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])

        experiment_query = ExperimentTrendQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendQuery",
            count_query=count_query,
            exposure_query=None,  # No exposure query provided
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02"},
                ],
                "user_out_of_control_exposure": [
                    {"event": "$feature_flag_called", "timestamp": "2020-01-02"},
                ],
                "user_out_of_date_range": [
                    {"event": "$pageview", "timestamp": "2019-01-01", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2019-01-01",
                        "properties": {ff_property: "control", "$feature_flag": feature_flag.key},
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendQueryRunner(
            query=ExperimentTrendQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendQueryResponse, result)

        self.assertIn("control", trend_result.results)
        self.assertIn("test", trend_result.results)

        control_result = trend_result.results["control"]
        test_result = trend_result.results["test"]

        self.assertEqual(control_result.count, 3)
        self.assertEqual(test_result.count, 5)

        self.assertEqual(control_result.exposure, 2)
        self.assertEqual(test_result.exposure, 2)
