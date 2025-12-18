from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    EventsNode,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentRetentionMetric,
    FunnelConversionWindowTimeUnit,
    StartHandling,
)

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from posthog.models import FeatureFlag
from posthog.test.test_journeys import journeys_for


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentRetentionMetric(ExperimentQueryRunnerBaseTest):
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_basic_retention_calculation(self):
        """
        Test basic retention metric: users who signed up and returned within 7 days.

        Retention = (users who completed) / (users who started) * 100%
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        # Create a retention metric:
        # Start event: signup
        # Completion event: login
        # Retention window: day 1 to day 7
        metric = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="signup",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="login",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group: 10 users exposed, 6 sign up, 4 of those return (4/6 = 66.7% retention)
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

            # First 6 users sign up (start event)
            if i < 6:
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: "control"},
                )

                # First 4 users return (completion event within retention window)
                if i < 4:
                    _create_event(
                        team=self.team,
                        event="login",
                        distinct_id=f"user_control_{i}",
                        timestamp="2020-01-05T12:00:00Z",  # Day 3 after signup
                        properties={feature_flag_property: "control"},
                    )

        # Test group: 10 users exposed, 8 sign up, 6 of those return (6/8 = 75% retention)
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

            # First 8 users sign up (start event)
            if i < 8:
                _create_event(
                    team=self.team,
                    event="signup",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: "test"},
                )

                # First 6 users return (completion event within retention window)
                if i < 6:
                    _create_event(
                        team=self.team,
                        event="login",
                        distinct_id=f"user_test_{i}",
                        timestamp="2020-01-05T12:00:00Z",  # Day 3 after signup
                        properties={feature_flag_property: "test"},
                    )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # Control: 6 users started (signed up), 4 retained (logged in)
        self.assertEqual(control_variant.number_of_samples, 6)
        self.assertEqual(control_variant.sum, 4)
        self.assertEqual(control_variant.sum_squares, 4)  # Binary: 1^2 = 1

        # Test: 8 users started (signed up), 6 retained (logged in)
        self.assertEqual(test_variant.number_of_samples, 8)
        self.assertEqual(test_variant.sum, 6)
        self.assertEqual(test_variant.sum_squares, 6)  # Binary: 1^2 = 1

        # Verify ratio-specific fields for control variant
        self.assertEqual(control_variant.denominator_sum, 6)  # 6 users started
        self.assertEqual(control_variant.denominator_sum_squares, 6)  # 6 (since 1^2 = 1)
        self.assertEqual(control_variant.numerator_denominator_sum_product, 4)  # 4 completed

        # Verify ratio-specific fields for test variant
        self.assertEqual(test_variant.denominator_sum, 8)  # 8 users started
        self.assertEqual(test_variant.denominator_sum_squares, 8)
        self.assertEqual(test_variant.numerator_denominator_sum_product, 6)  # 6 completed

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_retention_window_boundaries(self):
        """
        Test that retention window boundaries are enforced correctly.

        Window [7, 14] means:
        - Completion events on day 7-13 count (inclusive start, exclusive end)
        - Completion events before day 7 don't count
        - Completion events on day 14+ don't count
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Retention window: day 7 to day 14
        metric = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="signup",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="return_visit",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=7,
            retention_window_end=14,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        def _create_events_for_user(variant: str, user_id: str, completion_day_offset: int | None) -> list[dict]:
            """
            completion_day_offset: days after signup when user returns (None = doesn't return)
            """
            events = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02T12:00:00",
                    "properties": {
                        "$feature_flag_response": variant,
                        ff_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                },
                {
                    "event": "signup",
                    "timestamp": "2024-01-02T12:01:00",
                    "properties": {ff_property: variant},
                },
            ]

            if completion_day_offset is not None:
                events.append(
                    {
                        "event": "return_visit",
                        "timestamp": f"2024-01-{2 + completion_day_offset:02d}T12:01:00",
                        "properties": {ff_property: variant},
                    }
                )

            return events

        journeys_for(
            {
                # Control variant
                "control_1": _create_events_for_user("control", "user_c1", 5),  # Day 5 - TOO EARLY
                "control_2": _create_events_for_user("control", "user_c2", 7),  # Day 7 - COUNTS (start boundary)
                "control_3": _create_events_for_user("control", "user_c3", 10),  # Day 10 - COUNTS
                "control_4": _create_events_for_user("control", "user_c4", 13),  # Day 13 - COUNTS
                "control_5": _create_events_for_user(
                    "control", "user_c5", 14
                ),  # Day 14 - COUNTS (end boundary, inclusive)
                "control_6": _create_events_for_user("control", "user_c6", 20),  # Day 20 - TOO LATE
                "control_7": _create_events_for_user("control", "user_c7", None),  # Never returns
                # Test variant
                "test_1": _create_events_for_user("test", "user_t1", 6),  # Day 6 - TOO EARLY
                "test_2": _create_events_for_user("test", "user_t2", 7),  # Day 7 - COUNTS (start boundary)
                "test_3": _create_events_for_user("test", "user_t3", 9),  # Day 9 - COUNTS
                "test_4": _create_events_for_user("test", "user_t4", 12),  # Day 12 - COUNTS
                "test_5": _create_events_for_user("test", "user_t5", 13),  # Day 13 - COUNTS
                "test_6": _create_events_for_user("test", "user_t6", 14),  # Day 14 - COUNTS (end boundary, inclusive)
                "test_7": _create_events_for_user("test", "user_t7", None),  # Never returns
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # Control: 7 users started, 4 retained (days 7, 10, 13, 14 - all within [7,14] inclusive)
        self.assertEqual(control_variant.number_of_samples, 7)
        self.assertEqual(control_variant.sum, 4)

        # Test: 7 users started, 5 retained (days 7, 9, 12, 13, 14 - all within [7,14] inclusive)
        self.assertEqual(test_variant.number_of_samples, 7)
        self.assertEqual(test_variant.sum, 5)

        # Verify ratio-specific fields
        self.assertEqual(control_variant.denominator_sum, 7)
        self.assertEqual(control_variant.denominator_sum_squares, 7)
        self.assertEqual(control_variant.numerator_denominator_sum_product, 4)
        self.assertEqual(test_variant.denominator_sum, 7)
        self.assertEqual(test_variant.denominator_sum_squares, 7)
        self.assertEqual(test_variant.numerator_denominator_sum_product, 5)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_retention_first_seen_vs_last_seen(self):
        """
        Test start_handling: FIRST_SEEN vs LAST_SEEN for recurring start events.

        FIRST_SEEN: Use the first occurrence of start event
        LAST_SEEN: Use the last occurrence of start event
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create a retention metric with FIRST_SEEN
        metric_first_seen = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="signup",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
        )

        experiment_query_first = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric_first_seen,
        )

        def _create_events_for_user(variant: str, user_id: str) -> list[dict]:
            """
            User has multiple signup events and one purchase event.
            - First signup: Day 2
            - Second signup: Day 5
            - Purchase: Day 8

            With FIRST_SEEN (day 2 as reference):
            - Purchase on day 8 is 6 days later → WITHIN window [1, 7)

            With LAST_SEEN (day 5 as reference):
            - Purchase on day 8 is 3 days later → WITHIN window [1, 7)
            """
            return [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02T12:00:00",
                    "properties": {
                        "$feature_flag_response": variant,
                        ff_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                },
                {
                    "event": "signup",
                    "timestamp": "2024-01-02T12:01:00",  # First signup (day 0)
                    "properties": {ff_property: variant},
                },
                {
                    "event": "signup",
                    "timestamp": "2024-01-05T12:01:00",  # Second signup (day 3)
                    "properties": {ff_property: variant},
                },
                {
                    "event": "purchase",
                    "timestamp": "2024-01-08T12:01:00",  # Purchase (day 6)
                    "properties": {ff_property: variant},
                },
            ]

        journeys_for(
            {
                "control_1": _create_events_for_user("control", "user_c1"),
                "control_2": _create_events_for_user("control", "user_c2"),
                "test_1": _create_events_for_user("test", "user_t1"),
                "test_2": _create_events_for_user("test", "user_t2"),
            },
            self.team,
        )

        flush_persons_and_events()

        # Test with FIRST_SEEN
        query_runner = ExperimentQueryRunner(query=experiment_query_first, team=self.team)
        result_first = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result_first.baseline is not None
        assert result_first.variant_results is not None

        control_first = result_first.baseline
        test_first = result_first.variant_results[0]

        # With FIRST_SEEN: Purchase on day 6 (relative to first signup)
        # Window is [1, 7), so day 6 is WITHIN window
        self.assertEqual(control_first.number_of_samples, 2)
        self.assertEqual(control_first.sum, 2)  # Both users retained
        self.assertEqual(test_first.number_of_samples, 2)
        self.assertEqual(test_first.sum, 2)  # Both users retained

        # Verify ratio-specific fields for FIRST_SEEN
        self.assertEqual(control_first.denominator_sum, 2)
        self.assertEqual(control_first.denominator_sum_squares, 2)
        self.assertEqual(control_first.numerator_denominator_sum_product, 2)
        self.assertEqual(test_first.denominator_sum, 2)
        self.assertEqual(test_first.denominator_sum_squares, 2)
        self.assertEqual(test_first.numerator_denominator_sum_product, 2)

        # Now test with LAST_SEEN
        metric_last_seen = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="signup",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.LAST_SEEN,
        )

        experiment_query_last = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric_last_seen,
        )

        query_runner_last = ExperimentQueryRunner(query=experiment_query_last, team=self.team)
        result_last = cast(ExperimentQueryResponse, query_runner_last.calculate())

        assert result_last.baseline is not None
        assert result_last.variant_results is not None

        control_last = result_last.baseline
        test_last = result_last.variant_results[0]

        # With LAST_SEEN: Purchase on day 3 (relative to last signup on day 3)
        # Window is [1, 7), so day 3 is WITHIN window
        self.assertEqual(control_last.number_of_samples, 2)
        self.assertEqual(control_last.sum, 2)  # Both users retained
        self.assertEqual(test_last.number_of_samples, 2)
        self.assertEqual(test_last.sum, 2)  # Both users retained

        # Verify ratio-specific fields for LAST_SEEN
        self.assertEqual(control_last.denominator_sum, 2)
        self.assertEqual(control_last.denominator_sum_squares, 2)
        self.assertEqual(control_last.numerator_denominator_sum_product, 2)
        self.assertEqual(test_last.denominator_sum, 2)
        self.assertEqual(test_last.denominator_sum_squares, 2)
        self.assertEqual(test_last.numerator_denominator_sum_product, 2)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_retention_with_conversion_window(self):
        """
        Test retention metric with conversion window limiting start event search.

        Conversion window limits how long after exposure to look for the start event.
        Retention window is then measured from the start event (not exposure).
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create a retention metric with 2-hour conversion window
        metric = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="signup",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="return_visit",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=1,
            retention_window_end=3,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            conversion_window=2,
            conversion_window_unit=FunnelConversionWindowTimeUnit.HOUR,
            start_handling=StartHandling.FIRST_SEEN,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        def _create_events_for_user(
            variant: str, user_id: str, signup_hours_after_exposure: float, return_days_after_signup: int | None
        ) -> list[dict]:
            events = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02T12:00:00",
                    "properties": {
                        "$feature_flag_response": variant,
                        ff_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                },
            ]

            # Signup event at specified hours after exposure
            signup_hour = int(12 + signup_hours_after_exposure)
            signup_minute = int((signup_hours_after_exposure % 1) * 60)
            events.append(
                {
                    "event": "signup",
                    "timestamp": f"2024-01-02T{signup_hour:02d}:{signup_minute:02d}:00",
                    "properties": {ff_property: variant},
                }
            )

            # Return visit at specified days after signup
            if return_days_after_signup is not None:
                events.append(
                    {
                        "event": "return_visit",
                        "timestamp": f"2024-01-{2 + return_days_after_signup:02d}T14:00:00",
                        "properties": {ff_property: variant},
                    }
                )

            return events

        journeys_for(
            {
                # Control variant
                # Signup within window (1 hour), retention on day 2 (COUNTS)
                "control_1": _create_events_for_user("control", "user_c1", 1.0, 2),
                # Signup within window (1.5 hours), retention on day 2 (COUNTS)
                "control_2": _create_events_for_user("control", "user_c2", 1.5, 2),
                # Signup OUTSIDE window (3 hours), retention on day 2 (EXCLUDED - signup too late)
                "control_3": _create_events_for_user("control", "user_c3", 3.0, 2),
                # Signup within window (0.5 hours), no return (COUNTS as not retained)
                "control_4": _create_events_for_user("control", "user_c4", 0.5, None),
                # Test variant
                # Signup within window (1 hour), retention on day 2 (COUNTS)
                "test_1": _create_events_for_user("test", "user_t1", 1.0, 2),
                # Signup within window (2 hours exactly), retention on day 2 (COUNTS)
                "test_2": _create_events_for_user("test", "user_t2", 2.0, 2),
                # Signup OUTSIDE window (2.5 hours), retention on day 2 (EXCLUDED - signup too late)
                "test_3": _create_events_for_user("test", "user_t3", 2.5, 2),
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # Control: 3 users signed up within conversion window (c1, c2, c4)
        # 2 of them returned (c1, c2)
        self.assertEqual(control_variant.number_of_samples, 3)
        self.assertEqual(control_variant.sum, 2)

        # Test: 2 users signed up within conversion window (t1, t2)
        # Both returned
        self.assertEqual(test_variant.number_of_samples, 2)
        self.assertEqual(test_variant.sum, 2)

        # Verify ratio-specific fields
        self.assertEqual(control_variant.denominator_sum, 3)
        self.assertEqual(control_variant.denominator_sum_squares, 3)
        self.assertEqual(control_variant.numerator_denominator_sum_product, 2)
        self.assertEqual(test_variant.denominator_sum, 2)
        self.assertEqual(test_variant.denominator_sum_squares, 2)
        self.assertEqual(test_variant.numerator_denominator_sum_product, 2)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_retention_no_completion_events(self):
        """
        Test retention when users never complete (0% retention rate).
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        metric = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="signup",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="purchase",  # No one will have purchase events
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        def _create_events_for_user(variant: str, user_id: str) -> list[dict]:
            # Only exposure and start event, no completion event
            return [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02T12:00:00",
                    "properties": {
                        "$feature_flag_response": variant,
                        ff_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                },
                {
                    "event": "signup",
                    "timestamp": "2024-01-02T12:01:00",
                    "properties": {ff_property: variant},
                },
            ]

        journeys_for(
            {
                "control_1": _create_events_for_user("control", "user_c1"),
                "control_2": _create_events_for_user("control", "user_c2"),
                "control_3": _create_events_for_user("control", "user_c3"),
                "test_1": _create_events_for_user("test", "user_t1"),
                "test_2": _create_events_for_user("test", "user_t2"),
                "test_3": _create_events_for_user("test", "user_t3"),
                "test_4": _create_events_for_user("test", "user_t4"),
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # Control: 3 users started, 0 retained (0% retention)
        self.assertEqual(control_variant.number_of_samples, 3)
        self.assertEqual(control_variant.sum, 0)
        self.assertEqual(control_variant.sum_squares, 0)

        # Test: 4 users started, 0 retained (0% retention)
        self.assertEqual(test_variant.number_of_samples, 4)
        self.assertEqual(test_variant.sum, 0)
        self.assertEqual(test_variant.sum_squares, 0)

        # Verify ratio fields are populated even with 0% retention
        # Denominator should reflect users who started, numerator should be 0
        self.assertEqual(control_variant.denominator_sum, 3)  # 3 users started
        self.assertEqual(control_variant.denominator_sum_squares, 3)
        self.assertEqual(control_variant.numerator_denominator_sum_product, 0)  # 0 completed
        self.assertEqual(test_variant.denominator_sum, 4)  # 4 users started
        self.assertEqual(test_variant.denominator_sum_squares, 4)
        self.assertEqual(test_variant.numerator_denominator_sum_product, 0)  # 0 completed

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_retention_multiple_variants(self):
        """
        Test retention metric with multiple experiment variants (control + multiple tests).
        """
        # Create a feature flag with 3 variants
        feature_flag = FeatureFlag.objects.create(
            name="Test experiment flag with 3 variants",
            key="test-experiment-3-variants",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 33},
                        {"key": "test_a", "name": "Test A", "rollout_percentage": 33},
                        {"key": "test_b", "name": "Test B", "rollout_percentage": 34},
                    ]
                },
            },
            created_by=self.user,
        )

        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        metric = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="app_open",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="feature_used",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        def _create_events_for_user(variant: str, user_id: str, completes: bool) -> list[dict]:
            events = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02T12:00:00",
                    "properties": {
                        "$feature_flag_response": variant,
                        ff_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                },
                {
                    "event": "app_open",
                    "timestamp": "2024-01-02T12:01:00",
                    "properties": {ff_property: variant},
                },
            ]

            if completes:
                events.append(
                    {
                        "event": "feature_used",
                        "timestamp": "2024-01-05T12:00:00",  # Day 3
                        "properties": {ff_property: variant},
                    }
                )

            return events

        journeys_for(
            {
                # Control: 5 users, 3 retained (60%)
                "control_1": _create_events_for_user("control", "user_c1", True),
                "control_2": _create_events_for_user("control", "user_c2", True),
                "control_3": _create_events_for_user("control", "user_c3", True),
                "control_4": _create_events_for_user("control", "user_c4", False),
                "control_5": _create_events_for_user("control", "user_c5", False),
                # Test A: 4 users, 3 retained (75%)
                "test_a_1": _create_events_for_user("test_a", "user_ta1", True),
                "test_a_2": _create_events_for_user("test_a", "user_ta2", True),
                "test_a_3": _create_events_for_user("test_a", "user_ta3", True),
                "test_a_4": _create_events_for_user("test_a", "user_ta4", False),
                # Test B: 6 users, 5 retained (83.3%)
                "test_b_1": _create_events_for_user("test_b", "user_tb1", True),
                "test_b_2": _create_events_for_user("test_b", "user_tb2", True),
                "test_b_3": _create_events_for_user("test_b", "user_tb3", True),
                "test_b_4": _create_events_for_user("test_b", "user_tb4", True),
                "test_b_5": _create_events_for_user("test_b", "user_tb5", True),
                "test_b_6": _create_events_for_user("test_b", "user_tb6", False),
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 2)  # test_a and test_b

        control_variant = result.baseline
        test_a_variant = next(v for v in result.variant_results if v.key == "test_a")
        test_b_variant = next(v for v in result.variant_results if v.key == "test_b")

        # Control: 5 started, 3 retained
        self.assertEqual(control_variant.number_of_samples, 5)
        self.assertEqual(control_variant.sum, 3)

        # Test A: 4 started, 3 retained
        self.assertEqual(test_a_variant.number_of_samples, 4)
        self.assertEqual(test_a_variant.sum, 3)

        # Test B: 6 started, 5 retained
        self.assertEqual(test_b_variant.number_of_samples, 6)
        self.assertEqual(test_b_variant.sum, 5)

        # Verify ratio-specific fields for all three variants
        self.assertEqual(control_variant.denominator_sum, 5)
        self.assertEqual(control_variant.denominator_sum_squares, 5)
        self.assertEqual(control_variant.numerator_denominator_sum_product, 3)
        self.assertEqual(test_a_variant.denominator_sum, 4)
        self.assertEqual(test_a_variant.denominator_sum_squares, 4)
        self.assertEqual(test_a_variant.numerator_denominator_sum_product, 3)
        self.assertEqual(test_b_variant.denominator_sum, 6)
        self.assertEqual(test_b_variant.denominator_sum_squares, 6)
        self.assertEqual(test_b_variant.numerator_denominator_sum_product, 5)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_retention_day_zero_same_day_as_start(self):
        """
        Test Day 0 retention (same day as start event).

        Window [0, 0] should capture users who complete on the same day they started.
        This is a common activation metric: "Did user activate on signup day?"
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create a retention metric with [0, 0] window (same day as start)
        metric = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="signup",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="first_action",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=0,
            retention_window_end=0,  # Same day as start
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        def _create_events_for_user(variant: str, user_id: str, completion_hours_after_start: int | None) -> list[dict]:
            """
            completion_hours_after_start:
            - 0-23: Same day (day 0) - should be captured
            - 24+: Next day (day 1+) - should NOT be captured
            - None: Never completes
            """
            events = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02T10:00:00",
                    "properties": {
                        "$feature_flag_response": variant,
                        ff_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                },
                {
                    "event": "signup",
                    "timestamp": "2024-01-02T10:00:00",  # 10:00 AM on Jan 2
                    "properties": {ff_property: variant},
                },
            ]

            if completion_hours_after_start is not None:
                # Calculate timestamp for completion event
                if completion_hours_after_start < 24:
                    # Same day
                    hour = 10 + completion_hours_after_start
                    day = 2
                else:
                    # Next day(s)
                    hour = 10 + (completion_hours_after_start % 24)
                    day = 2 + (completion_hours_after_start // 24)

                events.append(
                    {
                        "event": "first_action",
                        "timestamp": f"2024-01-{day:02d}T{hour:02d}:00:00",
                        "properties": {ff_property: variant},
                    }
                )

            return events

        journeys_for(
            {
                # Control variant
                "control_1": _create_events_for_user("control", "user_c1", 2),  # Same day, 2 hours later - COUNTS
                "control_2": _create_events_for_user("control", "user_c2", 8),  # Same day, 8 hours later - COUNTS
                "control_3": _create_events_for_user("control", "user_c3", 13),  # Same day, 13 hours later - COUNTS
                "control_4": _create_events_for_user("control", "user_c4", 24),  # Next day - NOT counted
                "control_5": _create_events_for_user("control", "user_c5", None),  # Never completes - NOT counted
                # Test variant
                "test_1": _create_events_for_user("test", "user_t1", 1),  # Same day, 1 hour later - COUNTS
                "test_2": _create_events_for_user("test", "user_t2", 5),  # Same day, 5 hours later - COUNTS
                "test_3": _create_events_for_user("test", "user_t3", 24),  # Next day - NOT counted
                "test_4": _create_events_for_user("test", "user_t4", 48),  # 2 days later - NOT counted
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # Control: 5 users started, 3 completed same day (60%)
        self.assertEqual(control_variant.number_of_samples, 5)
        self.assertEqual(control_variant.sum, 3)
        self.assertEqual(control_variant.sum_squares, 3)

        # Test: 4 users started, 2 completed same day (50%)
        self.assertEqual(test_variant.number_of_samples, 4)
        self.assertEqual(test_variant.sum, 2)
        self.assertEqual(test_variant.sum_squares, 2)

        # Verify ratio-specific fields
        self.assertEqual(control_variant.denominator_sum, 5)
        self.assertEqual(control_variant.denominator_sum_squares, 5)
        self.assertEqual(control_variant.numerator_denominator_sum_product, 3)
        self.assertEqual(test_variant.denominator_sum, 4)
        self.assertEqual(test_variant.denominator_sum_squares, 4)
        self.assertEqual(test_variant.numerator_denominator_sum_product, 2)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_retention_hour_based_same_hour(self):
        """
        Test Hour-based retention with [0, 0] window (same hour as start).

        Window [0, 0] with HOUR unit should capture users who complete within
        the same hour they started (using toStartOfHour truncation).

        Example:
        - User starts at 10:15, completes at 10:45 → RETAINED (same hour: 10:00-10:59)
        - User starts at 10:59, completes at 11:01 → NOT RETAINED (different hour)
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create a retention metric with [0, 0] HOUR window
        metric = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="session_start",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="key_action",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=0,
            retention_window_end=0,  # Same hour as start
            retention_window_unit=FunnelConversionWindowTimeUnit.HOUR,
            start_handling=StartHandling.FIRST_SEEN,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        def _create_events_for_user(
            variant: str, user_id: str, start_minute: int, completion_minute_offset: int | None
        ) -> list[dict]:
            """
            start_minute: Minute of the hour when user starts (0-59)
            completion_minute_offset:
            - Positive within same hour: should be captured
            - Causes next hour: should NOT be captured
            - None: Never completes
            """
            events = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": f"2024-01-02T10:{start_minute:02d}:00",
                    "properties": {
                        "$feature_flag_response": variant,
                        ff_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                },
                {
                    "event": "session_start",
                    "timestamp": f"2024-01-02T10:{start_minute:02d}:00",
                    "properties": {ff_property: variant},
                },
            ]

            if completion_minute_offset is not None:
                completion_minute = start_minute + completion_minute_offset
                if completion_minute < 60:
                    # Same hour
                    events.append(
                        {
                            "event": "key_action",
                            "timestamp": f"2024-01-02T10:{completion_minute:02d}:00",
                            "properties": {ff_property: variant},
                        }
                    )
                else:
                    # Next hour(s)
                    hour = 10 + (completion_minute // 60)
                    minute = completion_minute % 60
                    events.append(
                        {
                            "event": "key_action",
                            "timestamp": f"2024-01-02T{hour:02d}:{minute:02d}:00",
                            "properties": {ff_property: variant},
                        }
                    )

            return events

        journeys_for(
            {
                # Control variant
                "control_1": _create_events_for_user("control", "user_c1", 10, 5),  # 10:10 → 10:15 (same hour) - COUNTS
                "control_2": _create_events_for_user(
                    "control", "user_c2", 15, 30
                ),  # 10:15 → 10:45 (same hour) - COUNTS
                "control_3": _create_events_for_user("control", "user_c3", 55, 4),  # 10:55 → 10:59 (same hour) - COUNTS
                "control_4": _create_events_for_user(
                    "control", "user_c4", 59, 2
                ),  # 10:59 → 11:01 (next hour) - NOT counted
                "control_5": _create_events_for_user("control", "user_c5", 30, None),  # Never completes - NOT counted
                # Test variant
                "test_1": _create_events_for_user("test", "user_t1", 0, 0),  # 10:00 → 10:00 (same minute) - COUNTS
                "test_2": _create_events_for_user("test", "user_t2", 20, 39),  # 10:20 → 10:59 (same hour) - COUNTS
                "test_3": _create_events_for_user("test", "user_t3", 45, 60),  # 10:45 → 11:45 (next hour) - NOT counted
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # Control: 5 users started, 3 completed in same hour (60%)
        self.assertEqual(control_variant.number_of_samples, 5)
        self.assertEqual(control_variant.sum, 3)
        self.assertEqual(control_variant.sum_squares, 3)

        # Test: 3 users started, 2 completed in same hour (66.7%)
        self.assertEqual(test_variant.number_of_samples, 3)
        self.assertEqual(test_variant.sum, 2)
        self.assertEqual(test_variant.sum_squares, 2)

        # Verify ratio-specific fields
        self.assertEqual(control_variant.denominator_sum, 5)
        self.assertEqual(control_variant.denominator_sum_squares, 5)
        self.assertEqual(control_variant.numerator_denominator_sum_product, 3)
        self.assertEqual(test_variant.denominator_sum, 3)
        self.assertEqual(test_variant.denominator_sum_squares, 3)
        self.assertEqual(test_variant.numerator_denominator_sum_product, 2)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_retention_multiple_completions_in_window(self):
        """
        Test that multiple completion events within the retention window are handled correctly.

        Users should be counted as retained (value = 1) even if they complete the event
        multiple times within the window. The MAX() aggregation in the query (line 1445
        in experiment_query_builder.py) ensures this.

        Scenario: User completes on day 3, day 5, and day 7 with window [1,7]
        Expected: User is retained (counted once), not counted 3 times
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        metric = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="signup",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        def _create_events_for_user(variant: str, user_id: str, completion_days: list[int] | None) -> list[dict]:
            """
            completion_days: List of days after signup when user completes
            - [3, 5, 7]: Multiple completions within window
            - [3]: Single completion
            - None or []: No completions
            """
            events = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02T12:00:00",
                    "properties": {
                        "$feature_flag_response": variant,
                        ff_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                },
                {
                    "event": "signup",
                    "timestamp": "2024-01-02T12:01:00",
                    "properties": {ff_property: variant},
                },
            ]

            if completion_days:
                for day_offset in completion_days:
                    events.append(
                        {
                            "event": "purchase",
                            "timestamp": f"2024-01-{2 + day_offset:02d}T14:00:00",
                            "properties": {ff_property: variant},
                        }
                    )

            return events

        journeys_for(
            {
                # Control variant
                "control_1": _create_events_for_user("control", "user_c1", [3, 5, 7]),  # 3 completions - COUNTS as 1
                "control_2": _create_events_for_user("control", "user_c2", [2, 4, 6]),  # 3 completions - COUNTS as 1
                "control_3": _create_events_for_user("control", "user_c3", [1, 1, 1]),  # Same day 3x - COUNTS as 1
                "control_4": _create_events_for_user("control", "user_c4", [4]),  # 1 completion - COUNTS as 1
                "control_5": _create_events_for_user("control", "user_c5", None),  # No completions - NOT counted
                "control_6": _create_events_for_user("control", "user_c6", [10, 12]),  # Outside window - NOT counted
                # Test variant
                "test_1": _create_events_for_user("test", "user_t1", [1, 3, 5, 7]),  # 4 completions - COUNTS as 1
                "test_2": _create_events_for_user("test", "user_t2", [2]),  # 1 completion - COUNTS as 1
                "test_3": _create_events_for_user("test", "user_t3", None),  # No completions - NOT counted
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # Control: 6 users started, 4 retained (even though they had multiple completions)
        # Each retained user counts as 1, not as sum of their completions
        self.assertEqual(control_variant.number_of_samples, 6)
        self.assertEqual(control_variant.sum, 4)  # 4 users retained, not 9 (total completions)
        self.assertEqual(control_variant.sum_squares, 4)  # 1^2 * 4 = 4

        # Test: 3 users started, 2 retained (even though they had multiple completions)
        self.assertEqual(test_variant.number_of_samples, 3)
        self.assertEqual(test_variant.sum, 2)  # 2 users retained, not 5 (total completions)
        self.assertEqual(test_variant.sum_squares, 2)  # 1^2 * 2 = 2

        # Verify ratio-specific fields
        self.assertEqual(control_variant.denominator_sum, 6)
        self.assertEqual(control_variant.denominator_sum_squares, 6)
        self.assertEqual(control_variant.numerator_denominator_sum_product, 4)
        self.assertEqual(test_variant.denominator_sum, 3)
        self.assertEqual(test_variant.denominator_sum_squares, 3)
        self.assertEqual(test_variant.numerator_denominator_sum_product, 2)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_retention_same_start_and_end_window(self, name, use_new_query_builder):
        """
        Test that retention window [N, N] captures events exactly on day N.
        This validates the fix for the half-open interval bug where [7,7] previously gave 0 results.

        User feedback: "I had to do [7,8] to capture events at exactly 7 days (10080 mins)"
        Fix: Changed query from < to <= to make interval closed [start, end] instead of half-open [start, end)
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        # Create a retention metric with [7, 7] window (same start and end)
        # This should capture events that happen exactly on day 7
        metric = ExperimentRetentionMetric(
            start_event=EventsNode(
                event="signup",
                math=ExperimentMetricMathType.TOTAL,
            ),
            completion_event=EventsNode(
                event="login",
                math=ExperimentMetricMathType.TOTAL,
            ),
            retention_window_start=7,
            retention_window_end=7,  # Same as start - should capture only day 7
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group: 4 users sign up, 2 return exactly on day 7
        for i in range(4):
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

            # All 4 users sign up
            _create_event(
                team=self.team,
                event="signup",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "control"},
            )

            # Users 0 and 1 return exactly on day 7 (should be captured by [7,7])
            if i < 2:
                _create_event(
                    team=self.team,
                    event="login",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-09T12:01:00Z",  # Exactly 7 days later
                    properties={feature_flag_property: "control"},
                )

            # User 2 returns on day 6 (should NOT be captured by [7,7])
            elif i == 2:
                _create_event(
                    team=self.team,
                    event="login",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-08T12:01:00Z",  # 6 days later
                    properties={feature_flag_property: "control"},
                )

            # User 3 returns on day 8 (should NOT be captured by [7,7])
            elif i == 3:
                _create_event(
                    team=self.team,
                    event="login",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-10T12:01:00Z",  # 8 days later
                    properties={feature_flag_property: "control"},
                )

        # Test group: 3 users sign up, all 3 return exactly on day 7
        for i in range(3):
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

            # All 3 users sign up
            _create_event(
                team=self.team,
                event="signup",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "test"},
            )

            # All 3 users return exactly on day 7
            _create_event(
                team=self.team,
                event="login",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-09T12:01:00Z",  # Exactly 7 days later
                properties={feature_flag_property: "test"},
            )

        flush_persons_and_events()

        runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = runner.calculate()

        assert isinstance(result, ExperimentQueryResponse)
        assert result.baseline is not None
        assert result.variant_results is not None
        assert len(result.variant_results) == 1

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # Control: 4 started, 2 retained (50% - only those on exactly day 7)
        self.assertEqual(control_variant.number_of_samples, 4)
        self.assertEqual(control_variant.sum, 2)

        # Test: 3 started, 3 retained (100% - all on exactly day 7)
        self.assertEqual(test_variant.number_of_samples, 3)
        self.assertEqual(test_variant.sum, 3)

        # Verify ratio-specific fields
        self.assertEqual(control_variant.denominator_sum, 4)
        self.assertEqual(control_variant.denominator_sum_squares, 4)
        self.assertEqual(control_variant.numerator_denominator_sum_product, 2)
        self.assertEqual(test_variant.denominator_sum, 3)
        self.assertEqual(test_variant.denominator_sum_squares, 3)
        self.assertEqual(test_variant.numerator_denominator_sum_product, 3)
