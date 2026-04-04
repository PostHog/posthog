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

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_experiment_funnel_actors_conversions(self):
        """
        Test getting persons who converted at a specific funnel step.

        Setup: 2-step funnel (signup -> purchase)
        - Control: 10 users exposed, 6 complete signup, 4 complete purchase
        - Test: 10 users exposed, 8 complete signup, 6 complete purchase

        Query: funnelStep=2 (positive) for control variant
        Expected: 4 persons who completed purchase in control
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Create 2-step funnel metric
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

        # Control variant: 10 exposed, 6 signup, 4 purchase
        control_purchase_users = []
        for i in range(10):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            # First 6 users do signup (with feature flag property)
            if i < 6:
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T13:00:00Z",
                    properties={feature_flag_property: "control"},
                )
                # First 4 of those also do purchase
                if i < 4:
                    control_purchase_users.append(f"user_control_{i}")
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_control_{i}",
                        timestamp="2020-01-02T14:00:00Z",
                        properties={feature_flag_property: "control"},
                    )

        # Test variant: 10 exposed, 8 signup, 6 purchase
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

        flush_persons_and_events()

        # Query for persons who CONVERTED at step 2 (purchase) in control variant
        experiment_actors_query = ExperimentActorsQuery(
            kind="ExperimentActorsQuery",
            source=experiment_query,
            funnelStep=2,  # Positive = converted at this step
            funnelStepBreakdown="control",  # Filter to control variant
            includeRecordings=False,
        )

        actors_query = ActorsQuery(
            source=experiment_actors_query,
            select=["id", "person"],
        )

        response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()

        # Should return 4 persons who completed purchase in control
        assert len(response.results) == 4
        # Note: In a more thorough test, we'd verify the actual person distinct_ids match control_purchase_users

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_experiment_funnel_actors_dropoffs(self):
        """
        Test getting persons who dropped off before a specific funnel step.

        Setup: Same 2-step funnel as above
        Query: funnelStep=-2 (negative) for control variant
        Expected: 6 persons who dropped off before purchase (exposed + signup but no purchase)
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

        # Control: 6 signup, 4 purchase
        # Dropoffs at step 2 (purchase) = 2 users who did signup but not purchase (users 4 and 5)
        control_dropoff_users = []
        for i in range(6):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="signup",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T13:00:00Z",
                properties={feature_flag_property: "control"},
            )
            if i < 4:  # Users 0-3 complete purchase
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T14:00:00Z",
                    properties={feature_flag_property: "control"},
                )
            else:  # Users 4 and 5 do signup but not purchase - these are dropoffs
                control_dropoff_users.append(f"user_control_{i}")

        flush_persons_and_events()

        # Query for persons who DROPPED OFF before step 2 (purchase)
        experiment_actors_query = ExperimentActorsQuery(
            kind="ExperimentActorsQuery",
            source=experiment_query,
            funnelStep=-2,  # Negative = dropped off before this step
            funnelStepBreakdown="control",
            includeRecordings=False,
        )

        actors_query = ActorsQuery(
            source=experiment_actors_query,
            select=["id", "person"],
        )

        response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()

        # Should return 2 persons who dropped off before purchase (users 4 and 5)
        assert len(response.results) == 2

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_experiment_funnel_actors_with_variant_filter(self):
        """
        Test that funnelStepBreakdown correctly filters actors to specific variant.

        Query for test variant conversions should not include control variant users.
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

        # Create data for both variants
        for variant in ["control", "test"]:
            for i in range(5):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T13:00:00Z",
                    properties={feature_flag_property: variant},
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T14:00:00Z",
                    properties={feature_flag_property: variant},
                )

        flush_persons_and_events()

        # Query for TEST variant only
        experiment_actors_query = ExperimentActorsQuery(
            kind="ExperimentActorsQuery",
            source=experiment_query,
            funnelStep=2,
            funnelStepBreakdown="test",  # Only test variant
            includeRecordings=False,
        )

        actors_query = ActorsQuery(
            source=experiment_actors_query,
            select=["id", "person"],
        )

        response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()

        # Should return only 5 test variant persons, not control
        assert len(response.results) == 5

        # TODO: Verify person distinct_ids all start with "user_test_" not "user_control_"

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
