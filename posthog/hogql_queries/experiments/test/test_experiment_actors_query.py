"""
Test Driven Development for ExperimentActorsQuery

This test file is written FIRST to define the behavior we want for experiment funnel actors queries.
The implementation will follow to make these tests pass.
"""

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import ActorsQuery, EventsNode, ExperimentActorsQuery, ExperimentFunnelMetric, ExperimentQuery

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentActorsQuery(ExperimentQueryRunnerBaseTest, ClickhouseTestMixin, APIBaseTest):
    """
    Test suite for ExperimentActorsQuery functionality.

    Tests that experiment funnel actors queries:
    1. Return persons who converted at specific steps (positive funnelStep)
    2. Return persons who dropped off before specific steps (negative funnelStep)
    3. Filter actors by specific variants (funnelStepBreakdown)
    4. Include matched recordings when requested
    """

    def _create_experiment_with_funnel(self):
        """Helper to create experiment with 2-step funnel metric."""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="signup"),
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

        return feature_flag, experiment, experiment_query

    def _create_funnel_data_both_variants(self, feature_flag_property: str):
        """Create test data: control (6 signup, 4 purchase) and test (8 signup, 6 purchase)."""
        for i in range(10):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            if i < 6:
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T13:00:00Z",
                    properties={feature_flag_property: "control"},
                )
                if i < 4:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_control_{i}",
                        timestamp="2020-01-02T14:00:00Z",
                        properties={feature_flag_property: "control"},
                    )

        for i in range(10):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            if i < 8:
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T13:00:00Z",
                    properties={feature_flag_property: "test"},
                )
                if i < 6:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_test_{i}",
                        timestamp="2020-01-02T14:00:00Z",
                        properties={feature_flag_property: "test"},
                    )

    @parameterized.expand(
        [
            ("conversions_control", 2, "control", 4),
            ("dropoffs_control", -2, "control", 2),
            ("conversions_test", 2, "test", 6),
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_experiment_funnel_actors(self, _name: str, funnel_step: int, variant: str, expected_count: int):
        """
        Test experiment funnel actors query for various combinations of step, variant, and conversion type.

        Positive funnelStep returns persons who converted at that step.
        Negative funnelStep returns persons who dropped off before that step.
        """
        feature_flag, _experiment, experiment_query = self._create_experiment_with_funnel()
        feature_flag_property = f"$feature/{feature_flag.key}"

        self._create_funnel_data_both_variants(feature_flag_property)
        flush_persons_and_events()

        experiment_actors_query = ExperimentActorsQuery(
            kind="ExperimentActorsQuery",
            source=experiment_query,
            funnelStep=funnel_step,
            funnelStepBreakdown=variant,
            includeRecordings=False,
        )

        actors_query = ActorsQuery(
            source=experiment_actors_query,
            select=["id", "person"],
        )

        response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()

        assert len(response.results) == expected_count

        distinct_ids = {row[1]["distinct_ids"][0] for row in response.results}
        for distinct_id in distinct_ids:
            assert distinct_id.startswith(f"user_{variant}_")

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_experiment_funnel_actors_with_recordings(self):
        """
        Test that includeRecordings=True returns matched_recordings field.

        This should match the behavior of regular funnel actors queries.
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="signup"),
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

        # Create a user with events (complete both funnel steps)
        _create_person(distinct_ids=["user_with_recording"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="signup",
            distinct_id="user_with_recording",
            timestamp="2020-01-02T13:00:00Z",
            properties={feature_flag_property: "control"},
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_with_recording",
            timestamp="2020-01-02T14:00:00Z",
            properties={feature_flag_property: "control"},
        )

        flush_persons_and_events()

        # Query with includeRecordings=True (query for step 2 conversions)
        experiment_actors_query = ExperimentActorsQuery(
            kind="ExperimentActorsQuery",
            source=experiment_query,
            funnelStep=2,  # Step 2 = purchase
            funnelStepBreakdown="control",
            includeRecordings=True,  # Request recordings
        )

        actors_query = ActorsQuery(
            source=experiment_actors_query,
            select=["id", "person", "matched_recordings"],
        )

        response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()

        # Should have matched_recordings in results (even if empty)
        assert len(response.results) == 1
        # Result format: [person_id, person_data, matched_recordings]
        assert len(response.results[0]) == 3
        # matched_recordings should be a list (may be empty if no actual recordings exist)
        assert isinstance(response.results[0][2], list)
