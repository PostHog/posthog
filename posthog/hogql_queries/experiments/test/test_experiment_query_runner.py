from django.test import override_settings
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.schema import (
    EventsNode,
    ExperimentSignificanceCode,
    ExperimentTrendsQuery,
    TrendsQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    flush_persons_and_events,
)
from freezegun import freeze_time
from django.utils import timezone
from datetime import timedelta
from posthog.test.test_journeys import journeys_for
from posthog.models.experiment import Experiment
from flaky import flaky


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

    def create_experiment(
        self,
        name="test-experiment",
        feature_flag=None,
        start_date=None,
        end_date=None,
    ):
        if feature_flag is None:
            feature_flag = self.create_feature_flag(name)
        if start_date is None:
            start_date = timezone.now()
        else:
            start_date = timezone.make_aware(start_date)  # Make naive datetime timezone-aware
        if end_date is None:
            end_date = timezone.now() + timedelta(days=14)
        elif end_date is not None:
            end_date = timezone.make_aware(end_date)  # Make naive datetime timezone-aware
        return Experiment.objects.create(
            name=name,
            team=self.team,
            feature_flag=feature_flag,
            start_date=start_date,
            end_date=end_date,
        )

    @flaky(max_runs=10, min_passes=1)
    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_standard_flow_v2_stats(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"version": 2}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
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
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        self.assertEqual(query_runner.stats_version, 2)
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

        self.assertAlmostEqual(result.credible_intervals["control"][0], 0.3633, delta=0.1)
        self.assertAlmostEqual(result.credible_intervals["control"][1], 2.9224, delta=0.1)
        self.assertAlmostEqual(result.credible_intervals["test"][0], 0.7339, delta=0.1)
        self.assertAlmostEqual(result.credible_intervals["test"][1], 3.8894, delta=0.1)

        self.assertAlmostEqual(result.p_value, 1.0, delta=0.1)

        self.assertAlmostEqual(result.probability["control"], 0.2549, delta=0.1)
        self.assertAlmostEqual(result.probability["test"], 0.7453, delta=0.1)

        self.assertEqual(result.significance_code, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)

        self.assertFalse(result.significant)

        self.assertEqual(len(result.variants), 2)

        self.assertEqual(control_variant.absolute_exposure, 2.0)
        self.assertEqual(control_variant.count, 3.0)
        # In the new query runner, the exposure value is the same as the absolute exposure value
        self.assertEqual(control_variant.exposure, 2.0)

        self.assertEqual(test_variant.absolute_exposure, 2.0)
        self.assertEqual(test_variant.count, 5.0)
        # In the new query runner, the exposure value is the same as the absolute exposure value
        self.assertEqual(test_variant.exposure, 2.0)
