from django.test import override_settings
from posthog.hogql_queries.experiments.experiment_trends_query_runner import ExperimentTrendsQueryRunner
from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.schema import (
    EventsNode,
    ExperimentSignificanceCode,
    ExperimentTrendsQuery,
    ExperimentTrendsQueryResponse,
    TrendsQuery,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from freezegun import freeze_time
from typing import cast
from django.utils import timezone
from datetime import timedelta
from posthog.test.test_journeys import journeys_for
from rest_framework.exceptions import ValidationError
from posthog.constants import ExperimentNoResultsErrorKeys
import json


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentTrendsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def create_feature_flag(self, key="test-experiment"):
        return FeatureFlag.objects.create(
            name=f"Test experiment flag: {key}",
            key=key,
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

    def create_experiment(self, name="test-experiment", feature_flag=None):
        if feature_flag is None:
            feature_flag = self.create_feature_flag(name)
        return Experiment.objects.create(
            name=name,
            team=self.team,
            feature_flag=feature_flag,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=14),
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        feature_flag_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
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

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in result.variants if variant.key == "control")
        test_result = next(variant for variant in result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 11)
        self.assertEqual(test_result.count, 15)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_custom_exposure(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        exposure_query = TrendsQuery(
            series=[EventsNode(event="custom_exposure_event", properties=[{"key": "valid_exposure", "value": "true"}])]
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
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

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 3)
        self.assertEqual(test_result.count, 5)

        self.assertEqual(control_result.absolute_exposure, 2)
        self.assertEqual(test_result.absolute_exposure, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_default_exposure(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
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

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 3)
        self.assertEqual(test_result.count, 5)

        self.assertEqual(control_result.absolute_exposure, 2)
        self.assertEqual(test_result.absolute_exposure, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_avg_math(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        count_query = TrendsQuery(series=[EventsNode(event="$pageview", math="avg")])
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )

        prepared_count_query = query_runner.prepared_count_query
        self.assertEqual(prepared_count_query.series[0].math, "sum")

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_standard_flow(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control"},
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control"},
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {ff_property: "test"}},
                    {"event": "$feature_flag_called", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {"event": "$feature_flag_called", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)
        for variant in result.variants:
            self.assertIn(variant.key, ["control", "test"])

        control_variant = next(v for v in result.variants if v.key == "control")
        test_variant = next(v for v in result.variants if v.key == "test")

        self.assertEqual(control_variant.count, 3)
        self.assertEqual(test_variant.count, 5)
        self.assertEqual(control_variant.absolute_exposure, 2)
        self.assertEqual(test_variant.absolute_exposure, 2)

        self.assertAlmostEqual(result.credible_intervals["control"][0], 0.5449, places=3)
        self.assertAlmostEqual(result.credible_intervals["control"][1], 4.3836, places=3)
        self.assertAlmostEqual(result.credible_intervals["test"][0], 1.1009, places=3)
        self.assertAlmostEqual(result.credible_intervals["test"][1], 5.8342, places=3)

        self.assertAlmostEqual(result.p_value, 1.0, places=3)

        self.assertAlmostEqual(result.probability["control"], 0.2549, places=2)
        self.assertAlmostEqual(result.probability["test"], 0.7453, places=2)

        self.assertEqual(result.significance_code, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)

        self.assertFalse(result.significant)

        self.assertEqual(len(result.variants), 2)

        self.assertEqual(control_variant.absolute_exposure, 2.0)
        self.assertEqual(control_variant.count, 3.0)
        self.assertEqual(control_variant.exposure, 1.0)

        self.assertEqual(test_variant.absolute_exposure, 2.0)
        self.assertEqual(test_variant.count, 5.0)
        self.assertEqual(test_variant.exposure, 1.0)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_events(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
        )

        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: True,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: True,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_control(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        journeys_for(
            {
                "user_test": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
        )

        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: False,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: False,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: False,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_test(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        journeys_for(
            {
                "user_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
        )

        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: False,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: False,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: False,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_flag_info(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        journeys_for(
            {
                "user_no_flag_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02"},
                ],
                "user_no_flag_2": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
        )

        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: True,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: True,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)
