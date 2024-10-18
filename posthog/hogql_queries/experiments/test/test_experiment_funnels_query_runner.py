from typing import cast
from posthog.hogql_queries.experiments.experiment_funnels_query_runner import ExperimentFunnelsQueryRunner
from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.schema import (
    EventsNode,
    ExperimentFunnelsQuery,
    ExperimentSignificanceCode,
    FunnelsQuery,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from freezegun import freeze_time
from django.utils import timezone
from datetime import timedelta
from rest_framework.exceptions import ValidationError
from posthog.constants import ExperimentNoResultsErrorKeys
import json
from posthog.test.test_journeys import journeys_for


class TestExperimentFunnelsQueryRunner(ClickhouseTestMixin, APIBaseTest):
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

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            source=funnels_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        for variant, purchase_count in [("control", 6), ("test", 8)]:
            for i in range(10):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={feature_flag_property: variant},
                )
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: variant},
                    )

        flush_persons_and_events()

        query_runner = ExperimentFunnelsQueryRunner(
            query=ExperimentFunnelsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)

        control_variant = next(variant for variant in result.variants if variant.key == "control")
        test_variant = next(variant for variant in result.variants if variant.key == "test")

        self.assertEqual(control_variant.success_count, 6)
        self.assertEqual(control_variant.failure_count, 4)
        self.assertEqual(test_variant.success_count, 8)
        self.assertEqual(test_variant.failure_count, 2)

        self.assertIn("control", result.probability)
        self.assertIn("test", result.probability)

        self.assertIn("control", result.credible_intervals)
        self.assertIn("test", result.credible_intervals)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_standard_flow(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            source=funnels_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "control"}},
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                ],
                "user_control_3": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "control"}},
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                ],
                "user_test_3": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                ],
                "user_test_4": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentFunnelsQueryRunner(
            query=ExperimentFunnelsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)
        for variant in result.variants:
            self.assertIn(variant.key, ["control", "test"])

        control_variant = next(v for v in result.variants if v.key == "control")
        test_variant = next(v for v in result.variants if v.key == "test")

        self.assertEqual(control_variant.success_count, 2)
        self.assertEqual(control_variant.failure_count, 1)
        self.assertEqual(test_variant.success_count, 3)
        self.assertEqual(test_variant.failure_count, 1)

        self.assertAlmostEqual(result.probability["control"], 0.407, places=2)
        self.assertAlmostEqual(result.probability["test"], 0.593, places=2)

        self.assertAlmostEqual(result.credible_intervals["control"][0], 0.1941, places=3)
        self.assertAlmostEqual(result.credible_intervals["control"][1], 0.9324, places=3)
        self.assertAlmostEqual(result.credible_intervals["test"][0], 0.2836, places=3)
        self.assertAlmostEqual(result.credible_intervals["test"][1], 0.9473, places=3)

        self.assertEqual(result.significance_code, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)

        self.assertFalse(result.significant)
        self.assertEqual(len(result.variants), 2)
        self.assertAlmostEqual(result.expected_loss, 1.0, places=1)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_events(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            source=funnels_query,
        )

        query_runner = ExperimentFunnelsQueryRunner(query=experiment_query, team=self.team)
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
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            source=funnels_query,
        )

        query_runner = ExperimentFunnelsQueryRunner(query=experiment_query, team=self.team)
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
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "control"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            source=funnels_query,
        )

        query_runner = ExperimentFunnelsQueryRunner(query=experiment_query, team=self.team)
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
                    {"event": "purchase", "timestamp": "2020-01-03"},
                ],
                "user_no_flag_2": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            source=funnels_query,
        )

        query_runner = ExperimentFunnelsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: False,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: True,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)
