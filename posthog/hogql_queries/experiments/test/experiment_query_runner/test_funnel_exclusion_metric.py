import uuid
from typing import cast

from freezegun import freeze_time
from posthog.test.base import (
    _create_event,
    _create_person,
    flush_persons_and_events,
)

from django.test import override_settings

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
        Test that users who perform the excluded event between funnel steps
        are not counted as conversions.

        Setup:
        - 3-step funnel: $feature_flag_called → $pageview → purchase
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
            # Exposure event
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
            # Step 1: pageview
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "control"},
            )
            # First 6 users purchase
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
            # Exposure event
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
            # Step 1: pageview
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "test"},
            )
            # First 8 users purchase
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

    @freeze_time("2020-01-01T12:00:00Z")
    def test_funnel_metric_without_exclusions_unchanged(self):
        """
        Verify that funnels without exclusions produce the same results as before.
        This is a regression test to ensure the exclusion code path doesn't
        affect existing behavior.
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Metric WITHOUT exclusions
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="purchase"),
            ],
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        for variant, success_count in [("control", 8), ("test", 10)]:
            for i in range(15):
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

        control_result = result.variants["control"]
        test_result = result.variants["test"]

        self.assertEqual(control_result["count"], 15)
        self.assertEqual(control_result["success_count"], 8)
        self.assertEqual(test_result["count"], 15)
        self.assertEqual(test_result["success_count"], 10)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_funnel_metric_exclusion_empty_list(self):
        """
        Verify that an empty exclusions list behaves identically to no exclusions.
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="purchase"),
            ],
            exclusions=[],  # Empty list
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        for variant, success_count in [("control", 5), ("test", 7)]:
            for i in range(10):
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

        control_result = result.variants["control"]
        test_result = result.variants["test"]

        self.assertEqual(control_result["count"], 10)
        self.assertEqual(control_result["success_count"], 5)
        self.assertEqual(test_result["count"], 10)
        self.assertEqual(test_result["success_count"], 7)
