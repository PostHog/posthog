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
        # Extract flag key from feature_flag_property ($feature/test-experiment -> test-experiment)
        flag_key = feature_flag_property.replace("$feature/", "")

        for i in range(10):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)

            # Add exposure event FIRST with correct $feature_flag_called properties
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    "$feature_flag": flag_key,  # The flag key
                    "$feature_flag_response": "control",  # The variant
                },
            )

            if i < 6:
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T13:00:00Z",  # After exposure
                    properties={feature_flag_property: "control"},
                )
                if i < 4:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_control_{i}",
                        timestamp="2020-01-02T14:00:00Z",  # After signup
                        properties={feature_flag_property: "control"},
                    )

        for i in range(10):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)

            # Add exposure event FIRST with correct $feature_flag_called properties
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    "$feature_flag": flag_key,  # The flag key
                    "$feature_flag_response": "test",  # The variant
                },
            )

            if i < 8:
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T13:00:00Z",  # After exposure
                    properties={feature_flag_property: "test"},
                )
                if i < 6:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_test_{i}",
                        timestamp="2020-01-02T14:00:00Z",  # After signup
                        properties={feature_flag_property: "test"},
                    )

    @parameterized.expand(
        [
            ("conversions_step1_control", 1, "control", 6),  # Step 1 conversions (signup)
            ("conversions_step2_control", 2, "control", 4),  # Step 2 conversions (purchase)
            ("dropoffs_control", -2, "control", 2),  # Step 2 drop-offs (signup but no purchase)
            ("conversions_step1_test", 1, "test", 8),  # Step 1 conversions (signup) - test variant
            ("conversions_step2_test", 2, "test", 6),  # Step 2 conversions (purchase) - test variant
            ("dropoffs_test", -2, "test", 2),  # Step 2 drop-offs - test variant
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

        # Exposure event first
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_with_recording",
            timestamp="2020-01-02T12:00:00Z",
            properties={
                "$feature_flag": feature_flag.key,
                "$feature_flag_response": "control",
            },
        )

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

    @freeze_time("2020-01-01T12:00:00Z")
    def test_experiment_funnel_actors_invalid_steps(self):
        """
        Test that invalid funnelStep values are properly rejected with helpful error messages.

        This test verifies that error messages:
        1. Explain WHY the step is invalid for experiment funnels specifically
        2. Show the experiment funnel structure (Exposure → Metric events)
        3. Provide the valid range of steps
        4. Use clear, actionable language

        Experiment funnels have unique constraints:
        - Exposure is step 0 in main query but excluded from actors query
        - funnelStep=-1 is invalid (would mean "exposed but never entered funnel")
        - funnelStep=0 is invalid (steps are 1-indexed)
        - Out-of-range steps should be rejected
        """
        feature_flag, experiment, experiment_query = self._create_experiment_with_funnel()

        # Test -1: Invalid drop-off (would mean "dropped before first metric step")
        # Error message should explain the experiment funnel structure and why this is invalid
        experiment_actors_query = ExperimentActorsQuery(
            kind="ExperimentActorsQuery",
            source=experiment_query,
            funnelStep=-1,
            funnelStepBreakdown="control",
            includeRecordings=False,
        )

        actors_query = ActorsQuery(
            source=experiment_actors_query,
            select=["id", "person"],
        )

        with self.assertRaises(Exception) as context:
            ActorsQueryRunner(query=actors_query, team=self.team).calculate()

        error_message = str(context.exception)
        # Verify error message contains all key information
        self.assertIn("Cannot query drop-offs before the first metric step", error_message)
        self.assertIn("experiment funnel", error_message.lower())
        self.assertIn("Exposure", error_message)  # Shows funnel structure
        self.assertIn("signup", error_message)  # Shows first metric event name
        self.assertIn("exposed but never entered the funnel", error_message)  # Explains WHY invalid
        self.assertIn("Valid drop-off steps: -2", error_message)  # Shows valid range
        self.assertIn("-3", error_message)  # Shows upper bound of valid range

        # Test 0: Invalid step (steps are 1-indexed)
        # Error message should explain that step 0 doesn't exist and show valid range
        experiment_actors_query_zero = ExperimentActorsQuery(
            kind="ExperimentActorsQuery",
            source=experiment_query,
            funnelStep=0,
            funnelStepBreakdown="control",
            includeRecordings=False,
        )

        actors_query_zero = ActorsQuery(
            source=experiment_actors_query_zero,
            select=["id", "person"],
        )

        with self.assertRaises(Exception) as context:
            ActorsQueryRunner(query=actors_query_zero, team=self.team).calculate()

        error_message = str(context.exception)
        self.assertIn("Funnel steps are 1-indexed", error_message)
        self.assertIn("Step 0 does not exist", error_message)
        self.assertIn("Valid conversion steps: 1", error_message)  # Shows start of valid range
        self.assertIn("2", error_message)  # Shows end of valid range (2 metric steps)

        # Test out-of-range drop-off (2-step funnel, so -3 is last valid, -4 is invalid)
        # Error message should show the invalid step, number of metric steps, and valid range
        experiment_actors_query_out_of_range = ExperimentActorsQuery(
            kind="ExperimentActorsQuery",
            source=experiment_query,
            funnelStep=-4,  # Too many steps back for a 2-step funnel
            funnelStepBreakdown="control",
            includeRecordings=False,
        )

        actors_query_out_of_range = ActorsQuery(
            source=experiment_actors_query_out_of_range,
            select=["id", "person"],
        )

        with self.assertRaises(Exception) as context:
            ActorsQueryRunner(query=actors_query_out_of_range, team=self.team).calculate()

        error_message = str(context.exception)
        self.assertIn("Invalid drop-off step -4", error_message)  # Shows the invalid value
        self.assertIn("2 metric steps", error_message)  # Shows context
        self.assertIn("Valid drop-off steps: -2", error_message)  # Shows valid range start
        self.assertIn("-3", error_message)  # Shows valid range end

        # Test out-of-range conversion (2-step funnel, so 3 is invalid)
        # Error message should show the invalid step, number of metric steps, and valid range
        experiment_actors_query_high_step = ExperimentActorsQuery(
            kind="ExperimentActorsQuery",
            source=experiment_query,
            funnelStep=3,  # Only 2 metric steps exist
            funnelStepBreakdown="control",
            includeRecordings=False,
        )

        actors_query_high_step = ActorsQuery(
            source=experiment_actors_query_high_step,
            select=["id", "person"],
        )

        with self.assertRaises(Exception) as context:
            ActorsQueryRunner(query=actors_query_high_step, team=self.team).calculate()

        error_message = str(context.exception)
        self.assertIn("Invalid conversion step 3", error_message)  # Shows the invalid value
        self.assertIn("2 metric steps", error_message)  # Shows context
        self.assertIn("Valid conversion steps: 1", error_message)  # Shows valid range start
        self.assertIn("(first metric step) to 2", error_message)  # Shows valid range end with explanation

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_experiment_funnel_actors_excludes_events_before_exposure(self):
        """
        Test that actors query only counts events AFTER exposure, matching main query behavior.

        Scenario:
        - User does $pageview BEFORE being exposed
        - User gets exposed
        - User never does purchase

        Expected:
        - Main query: NOT counted as drop-off (pageview was before exposure)
        - Actors query: Also NOT counted (with fix applied)
        """
        feature_flag, experiment, experiment_query = self._create_experiment_with_funnel()

        # Create user who did events BEFORE exposure
        _create_person(distinct_ids=["user_before_exposure"], team_id=self.team.pk)

        # Event BEFORE exposure (should be ignored)
        _create_event(
            team=self.team,
            event="signup",
            distinct_id="user_before_exposure",
            timestamp="2020-01-02T10:00:00Z",  # Before exposure
        )

        # Exposure event with correct properties for $feature_flag_called
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_before_exposure",
            timestamp="2020-01-02T12:00:00Z",  # Exposure
            properties={
                "$feature_flag": feature_flag.key,
                "$feature_flag_response": "control",
            },
        )

        # No purchase event

        # Create user who did events AFTER exposure (should be counted)
        _create_person(distinct_ids=["user_after_exposure"], team_id=self.team.pk)

        # Exposure event with correct properties for $feature_flag_called
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_after_exposure",
            timestamp="2020-01-02T12:00:00Z",  # Exposure
            properties={
                "$feature_flag": feature_flag.key,
                "$feature_flag_response": "control",
            },
        )

        # Event AFTER exposure (should be counted)
        _create_event(
            team=self.team,
            event="signup",
            distinct_id="user_after_exposure",
            timestamp="2020-01-02T13:00:00Z",  # After exposure
        )

        # No purchase event

        flush_persons_and_events()

        # Query for step 2 drop-offs (did signup after exposure, but no purchase)
        experiment_actors_query = ExperimentActorsQuery(
            kind="ExperimentActorsQuery",
            source=experiment_query,
            funnelStep=-2,  # Drop-offs at step 2
            funnelStepBreakdown="control",
            includeRecordings=False,
        )

        actors_query = ActorsQuery(
            source=experiment_actors_query,
            select=["id", "person"],
        )

        response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()

        # Should only return 1 user (user_after_exposure)
        # user_before_exposure should NOT be counted because their signup was before exposure
        assert len(response.results) == 1
        assert response.results[0][1]["distinct_ids"][0] == "user_after_exposure"
