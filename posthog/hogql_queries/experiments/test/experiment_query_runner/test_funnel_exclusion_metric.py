from typing import cast

from freezegun import freeze_time
from posthog.test.base import (
    _create_event,
    _create_person,
    flush_persons_and_events,
)

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentQuery,
    ExperimentQueryResponse,
    FunnelExclusionEventsNode,
)

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentFunnelExclusionMetric(ExperimentQueryRunnerBaseTest):
    """
    Tests for funnel exclusion steps in experiment metrics.

    Exclusion steps filter out users who performed a specific event between
    funnel steps. Users who trigger the excluded event are disqualified from
    counting as conversions.
    """

    @freeze_time("2020-01-01T12:00:00Z")
    def test_funnel_metric_with_exclusion_step(self):
        """
        Users who perform the excluded event between funnel steps
        are not counted as conversions.

        Setup:
        - 3-step funnel: $feature_flag_called -> $pageview -> purchase
        - Exclusion: "help_article_viewed" between step 0 and step 2
        - Control: 10 users, 6 purchase, 2 of those 6 also view help article
        - Test: 10 users, 8 purchase, 1 of those 8 also views help article

        Expected:
        - Control: 4 conversions (6 purchases - 2 excluded)
        - Test: 7 conversions (8 purchases - 1 excluded)
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview"),
                EventsNode(event="purchase"),
            ],
            exclusions=[
                FunnelExclusionEventsNode(
                    event="help_article_viewed",
                    funnelFromStep=0,
                    funnelToStep=2,
                ),
            ],
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Control: 10 users
        for i in range(10):
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
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "control"},
            )
            if i < 6:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T12:02:00Z",
                    properties={feature_flag_property: "control"},
                )
            # Users 4 and 5 also view help article (should be excluded)
            if i in (4, 5):
                _create_event(
                    team=self.team,
                    event="help_article_viewed",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T12:01:30Z",
                    properties={feature_flag_property: "control"},
                )

        # Test: 10 users
        for i in range(10):
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
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "test"},
            )
            if i < 8:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T12:02:00Z",
                    properties={feature_flag_property: "test"},
                )
            # User 7 also views help article (should be excluded)
            if i == 7:
                _create_event(
                    team=self.team,
                    event="help_article_viewed",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T12:01:30Z",
                    properties={feature_flag_property: "test"},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(
            query=experiment_query, team=self.team
        )
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        control_result = result.variants["control"]
        test_result = result.variants["test"]

        # Control: 10 exposed, 4 converted (6 purchased - 2 excluded)
        self.assertEqual(control_result["count"], 10)
        self.assertEqual(control_result["absolute_exposure"], 10)
        self.assertEqual(control_result["success_count"], 4)

        # Test: 10 exposed, 7 converted (8 purchased - 1 excluded)
        self.assertEqual(test_result["count"], 10)
        self.assertEqual(test_result["absolute_exposure"], 10)
        self.assertEqual(test_result["success_count"], 7)

    @parameterized.expand([
        ("no_exclusions_field", None, [("control", 8, 15), ("test", 10, 15)]),
        ("empty_exclusions_list", [], [("control", 5, 10), ("test", 7, 10)]),
    ])
    @freeze_time("2020-01-01T12:00:00Z")
    def test_funnel_metric_without_active_exclusions(self, _name, exclusions, expected):
        """
        Funnels without exclusions (or with an empty list) produce the same
        results as before — regression test.
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric_kwargs = {"series": [EventsNode(event="purchase")]}
        if exclusions is not None:
            metric_kwargs["exclusions"] = exclusions
        metric = ExperimentFunnelMetric(**metric_kwargs)

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        for variant, success_count, total in expected:
            for i in range(total):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
                if i < success_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: variant},
                    )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(
            query=experiment_query, team=self.team
        )
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        for variant, success_count, total in expected:
            variant_result = result.variants[variant]
            self.assertEqual(variant_result["count"], total)
            self.assertEqual(variant_result["success_count"], success_count)
