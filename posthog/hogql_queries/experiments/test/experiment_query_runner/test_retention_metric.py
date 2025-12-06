from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries

from django.test import override_settings

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
                "control_2": _create_events_for_user("control", "user_c2", 7),  # Day 7 - COUNTS
                "control_3": _create_events_for_user("control", "user_c3", 10),  # Day 10 - COUNTS
                "control_4": _create_events_for_user("control", "user_c4", 13),  # Day 13 - COUNTS
                "control_5": _create_events_for_user("control", "user_c5", 14),  # Day 14 - TOO LATE
                "control_6": _create_events_for_user("control", "user_c6", 20),  # Day 20 - TOO LATE
                "control_7": _create_events_for_user("control", "user_c7", None),  # Never returns
                # Test variant
                "test_1": _create_events_for_user("test", "user_t1", 6),  # Day 6 - TOO EARLY
                "test_2": _create_events_for_user("test", "user_t2", 7),  # Day 7 - COUNTS
                "test_3": _create_events_for_user("test", "user_t3", 9),  # Day 9 - COUNTS
                "test_4": _create_events_for_user("test", "user_t4", 12),  # Day 12 - COUNTS
                "test_5": _create_events_for_user("test", "user_t5", 13),  # Day 13 - COUNTS
                "test_6": _create_events_for_user("test", "user_t6", 14),  # Day 14 - TOO LATE
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

        # Control: 7 users started, 3 retained (days 7, 10, 13)
        self.assertEqual(control_variant.number_of_samples, 7)
        self.assertEqual(control_variant.sum, 3)

        # Test: 7 users started, 4 retained (days 7, 9, 12, 13)
        self.assertEqual(test_variant.number_of_samples, 7)
        self.assertEqual(test_variant.sum, 4)

        # Verify ratio-specific fields
        self.assertEqual(control_variant.denominator_sum, 7)
        self.assertEqual(control_variant.denominator_sum_squares, 7)
        self.assertEqual(control_variant.numerator_denominator_sum_product, 3)
        self.assertEqual(test_variant.denominator_sum, 7)
        self.assertEqual(test_variant.denominator_sum_squares, 7)
        self.assertEqual(test_variant.numerator_denominator_sum_product, 4)

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
