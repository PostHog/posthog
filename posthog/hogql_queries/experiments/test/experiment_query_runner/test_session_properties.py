"""
Tests for session property aggregation in experiment metrics.

These tests verify that session properties (like $session_duration) are correctly
aggregated in experiments, avoiding the multiplication bug where each event in a
session contributes the full session value instead of deduplicating per session.
"""

from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
)

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from posthog.models.utils import uuid7


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentSessionPropertyMetrics(ExperimentQueryRunnerBaseTest):
    """Tests for session property aggregation in experiments."""

    @freeze_time("2024-01-01T12:00:00Z")
    def test_session_duration_not_multiplied_across_events(self):
        """
        Critical test: Verify session duration is NOT multiplied by event count.

        Setup:
        - Control user: 1 session of 60 seconds with 3 pageviews
        - Test user: 1 session of 120 seconds with 2 pageviews

        Expected (correct):
        - Control sum: 60 (one session contributes 60s once)
        - Test sum: 120 (one session contributes 120s once)

        Bug behavior (what currently happens):
        - Control sum: 180 (60s * 3 pageviews = each event contributes full duration)
        - Test sum: 240 (120s * 2 pageviews)

        This test should FAIL initially, proving the bug exists.
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create session IDs
        control_session_id = str(uuid7("2024-01-02"))
        test_session_id = str(uuid7("2024-01-02"))

        # Control user: 1 session with 3 pageviews
        # Session duration = 60s (from first pageview to last pageview)
        # Exposure is in a DIFFERENT session to isolate the metric session
        _create_person(distinct_ids=["control_user"], team_id=self.team.pk)

        # Exposure event (in its own session, before the metric session)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="control_user",
            timestamp="2024-01-02T11:00:00Z",  # 1 hour before metric events
            properties={
                "$feature_flag_response": "control",
                ff_property: "control",
                "$feature_flag": feature_flag.key,
                "$session_id": f"{control_session_id}_exposure",  # Different session
            },
        )

        # 3 pageviews in the metric session, spanning 60 seconds
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="control_user",
            timestamp="2024-01-02T12:00:00Z",  # Session start
            properties={ff_property: "control", "$session_id": control_session_id},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="control_user",
            timestamp="2024-01-02T12:00:30Z",  # T+30s
            properties={ff_property: "control", "$session_id": control_session_id},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="control_user",
            timestamp="2024-01-02T12:01:00Z",  # T+60s (session duration = 60s)
            properties={ff_property: "control", "$session_id": control_session_id},
        )

        # Test user: 1 session with 2 pageviews
        # Session duration = 120s (from first pageview to last pageview)
        _create_person(distinct_ids=["test_user"], team_id=self.team.pk)

        # Exposure event (in its own session, before the metric session)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="test_user",
            timestamp="2024-01-02T11:00:00Z",  # 1 hour before metric events
            properties={
                "$feature_flag_response": "test",
                ff_property: "test",
                "$feature_flag": feature_flag.key,
                "$session_id": f"{test_session_id}_exposure",  # Different session
            },
        )

        # 2 pageviews in the metric session, spanning 120 seconds
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test_user",
            timestamp="2024-01-02T12:00:00Z",  # Session start
            properties={ff_property: "test", "$session_id": test_session_id},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test_user",
            timestamp="2024-01-02T12:02:00Z",  # T+120s (session duration = 120s)
            properties={ff_property: "test", "$session_id": test_session_id},
        )

        flush_persons_and_events()

        # Create metric using session property
        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="$pageview",
                math=ExperimentMetricMathType.SUM,
                math_property="$session_duration",
                math_property_type="session_properties",
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # These assertions represent the CORRECT behavior
        # Control: 1 session * 60 seconds = 60
        # Test: 1 session * 120 seconds = 120
        #
        # If the bug exists, we'd see:
        # Control: 3 events * 60 seconds = 180 (WRONG)
        # Test: 2 events * 120 seconds = 240 (WRONG)
        self.assertEqual(control_variant.sum, 60, "Control session duration should be 60s (not multiplied by 3 events)")
        self.assertEqual(test_variant.sum, 120, "Test session duration should be 120s (not multiplied by 2 events)")

        # Each variant has 1 user
        self.assertEqual(control_variant.number_of_samples, 1)
        self.assertEqual(test_variant.number_of_samples, 1)
