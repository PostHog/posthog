from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries

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
    @snapshot_clickhouse_queries
    @freeze_time("2024-01-01T12:00:00Z")
    def test_session_duration_not_multiplied_across_events(self):
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
        assert len(result.variant_results) == 1

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        assert control_variant.sum == 60
        assert test_variant.sum == 120
        assert control_variant.number_of_samples == 1
        assert test_variant.number_of_samples == 1

    @freeze_time("2024-01-01T12:00:00Z")
    def test_multiple_sessions_per_user_sums_correctly(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"
        session_1 = str(uuid7("2024-01-02"))
        session_2 = str(uuid7("2024-01-02"))

        _create_person(distinct_ids=["user"], team_id=self.team.pk)

        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user",
            timestamp="2024-01-02T11:00:00Z",
            properties={
                "$feature_flag_response": "test",
                ff_property: "test",
                "$feature_flag": feature_flag.key,
                "$session_id": f"{session_1}_exposure",
            },
        )

        # Session 1: 60s duration with 2 pageviews
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user",
            timestamp="2024-01-02T12:00:00Z",
            properties={ff_property: "test", "$session_id": session_1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user",
            timestamp="2024-01-02T12:01:00Z",
            properties={ff_property: "test", "$session_id": session_1},
        )

        # Session 2: 120s duration with 2 pageviews
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user",
            timestamp="2024-01-02T13:00:00Z",
            properties={ff_property: "test", "$session_id": session_2},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user",
            timestamp="2024-01-02T13:02:00Z",
            properties={ff_property: "test", "$session_id": session_2},
        )

        flush_persons_and_events()

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

        assert result.variant_results is not None
        assert len(result.variant_results) == 1

        test_variant = result.variant_results[0]
        # Sum of both sessions: 60 + 120 = 180 (not 60*2 + 120*2 = 360)
        assert test_variant.sum == 180
        assert test_variant.number_of_samples == 1

    @freeze_time("2024-01-01T12:00:00Z")
    def test_session_duration_backwards_compat_without_property_type(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"
        session_id = str(uuid7("2024-01-02"))

        _create_person(distinct_ids=["user"], team_id=self.team.pk)

        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user",
            timestamp="2024-01-02T11:00:00Z",
            properties={
                "$feature_flag_response": "test",
                ff_property: "test",
                "$feature_flag": feature_flag.key,
                "$session_id": f"{session_id}_exposure",
            },
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user",
            timestamp="2024-01-02T12:00:00Z",
            properties={ff_property: "test", "$session_id": session_id},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user",
            timestamp="2024-01-02T12:01:00Z",
            properties={ff_property: "test", "$session_id": session_id},
        )

        flush_persons_and_events()

        # No math_property_type specified - should still work for $session_duration
        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="$pageview",
                math=ExperimentMetricMathType.SUM,
                math_property="$session_duration",
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

        assert result.variant_results is not None
        test_variant = result.variant_results[0]
        assert test_variant.sum == 60
        assert test_variant.number_of_samples == 1
