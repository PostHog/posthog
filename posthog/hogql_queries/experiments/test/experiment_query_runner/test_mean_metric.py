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
from posthog.test.test_journeys import journeys_for


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentMeanMetric(ExperimentQueryRunnerBaseTest):
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_property_sum_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Create events with different amounts for control vs test to provide variance
        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control: 6 purchases with amount 10 (total 60)
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
            if i < 6:  # First 6 users make purchases
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: "control", "amount": 10},
                )

        # Test: 8 purchases with amount 15 (total 120)
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
            if i < 8:  # First 8 users make purchases
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: "test", "amount": 15},
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        self.assertEqual(control_variant.sum, 60)
        self.assertEqual(test_variant.sum, 120)
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_outlier_handling_for_sum_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        def _create_events_for_user(variant: str, amount: int) -> list[dict]:
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
                    "event": "purchase",
                    "timestamp": "2024-01-02T12:01:00",
                    "properties": {
                        ff_property: variant,
                        "amount": amount,
                    },
                },
            ]

        journeys_for(
            {
                "control_1": _create_events_for_user("control", 1),
                "control_2": _create_events_for_user("control", 102),
                "control_3": _create_events_for_user("control", 103),
                "control_4": _create_events_for_user("control", 104),
                "control_5": _create_events_for_user("control", 105),
                "control_6": _create_events_for_user("control", 106),
                "control_7": _create_events_for_user("control", 107),
                "control_8": _create_events_for_user("control", 108),
                "control_9": _create_events_for_user("control", 109),
                "control_10": _create_events_for_user("control", 1110),
                "test_1": _create_events_for_user("test", 101),
                "test_2": _create_events_for_user("test", 102),
                "test_3": _create_events_for_user("test", 103),
                "test_4": _create_events_for_user("test", 104),
                "test_5": _create_events_for_user("test", 105),
                "test_6": _create_events_for_user("test", 106),
                "test_7": _create_events_for_user("test", 107),
                "test_8": _create_events_for_user("test", 108),
                "test_9": _create_events_for_user("test", 109),
                "test_10": _create_events_for_user("test", 110),
            },
            self.team,
        )

        flush_persons_and_events()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            lower_bound_percentile=0.1,
            upper_bound_percentile=0.9,
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

        self.assertEqual(control_variant.sum, 1055)
        self.assertEqual(test_variant.sum, 1055)
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_outlier_handling_for_count_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        def _create_events_for_user(variant: str, count: int) -> list[dict]:
            purchase_events = [
                {
                    "event": "purchase",
                    "timestamp": f"2024-01-02T12:01:{i:02d}",
                    "properties": {
                        ff_property: variant,
                    },
                }
                for i in range(count)
            ]
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
                *purchase_events,
            ]

        journeys_for(
            {
                "control_1": _create_events_for_user("control", 1),
                "control_2": _create_events_for_user("control", 3),
                "control_3": _create_events_for_user("control", 3),
                "control_4": _create_events_for_user("control", 3),
                "control_5": _create_events_for_user("control", 3),
                "control_6": _create_events_for_user("control", 3),
                "control_7": _create_events_for_user("control", 3),
                "control_8": _create_events_for_user("control", 3),
                "control_9": _create_events_for_user("control", 3),
                "control_10": _create_events_for_user("control", 100),
                "test_1": _create_events_for_user("test", 2),
                "test_2": _create_events_for_user("test", 4),
                "test_3": _create_events_for_user("test", 4),
                "test_4": _create_events_for_user("test", 4),
                "test_5": _create_events_for_user("test", 4),
                "test_6": _create_events_for_user("test", 4),
                "test_7": _create_events_for_user("test", 4),
                "test_8": _create_events_for_user("test", 4),
                "test_9": _create_events_for_user("test", 4),
                "test_10": _create_events_for_user("test", 4),
            },
            self.team,
        )

        flush_persons_and_events()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.TOTAL,
            ),
            lower_bound_percentile=0.1,
            upper_bound_percentile=0.9,
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

        self.assertEqual(control_variant.sum, 30.9)
        self.assertEqual(test_variant.sum, 38.9)
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_unique_sessions_math_type(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        def _create_events_for_user(variant: str, count: int, session_id: str) -> list[dict]:
            pageview_events = [
                {
                    "event": "$pageview",
                    "timestamp": f"2024-01-02T12:01:{i:02d}",
                    "properties": {
                        ff_property: variant,
                        "$session_id": session_id,
                    },
                }
                for i in range(count)
            ]
            return [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02T12:00:00",
                    "properties": {
                        "$feature_flag_response": variant,
                        ff_property: variant,
                        "$feature_flag": feature_flag.key,
                        "$session_id": session_id,
                    },
                },
                *pageview_events,
            ]

        journeys_for(
            {
                # 3 unique sessions in control
                "control_1": [
                    *_create_events_for_user("control", 3, "c_1_a"),
                    *_create_events_for_user("control", 3, "c_1_b"),
                ],
                "control_2": _create_events_for_user("control", 3, "c_2_a"),
                # Control 3 has zero pageviews, so this session should not be included in the session metric count
                "control_3": _create_events_for_user("control", 0, "c_3_a"),
                # 5 unique sessions in test
                "test_1": [
                    *_create_events_for_user("test", 3, "t_1_a"),
                    *_create_events_for_user("test", 3, "t_1_b"),
                ],
                "test_2": [
                    *_create_events_for_user("test", 3, "t_2_a"),
                    *_create_events_for_user("test", 3, "t_2_b"),
                    *_create_events_for_user("test", 3, "t_2_c"),
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="$pageview",
                math=ExperimentMetricMathType.UNIQUE_SESSION,
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

        self.assertEqual(control_variant.sum, 3)
        self.assertEqual(test_variant.sum, 5)
        self.assertEqual(control_variant.number_of_samples, 3)
        self.assertEqual(test_variant.number_of_samples, 2)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_property_max_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        def _create_events_for_user(variant: str, amounts: list[int]) -> list[dict]:
            purchase_events = [
                {
                    "event": "purchase",
                    "timestamp": f"2024-01-02T12:01:{i:02d}",
                    "properties": {
                        ff_property: variant,
                        "amount": amount,
                    },
                }
                for i, amount in enumerate(amounts)
            ]
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
                *purchase_events,
            ]

        journeys_for(
            {
                "control_1": _create_events_for_user("control", [10, 20, 30]),
                "control_2": _create_events_for_user("control", [5, 15, 25]),
                "test_1": _create_events_for_user("test", [50, 60, 70]),
                "test_2": _create_events_for_user("test", [40, 80, 90]),
            },
            self.team,
        )

        flush_persons_and_events()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.MAX,
                math_property="amount",
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

        self.assertEqual(control_variant.sum, 55)
        self.assertEqual(test_variant.sum, 160)
        self.assertEqual(control_variant.number_of_samples, 2)
        self.assertEqual(test_variant.number_of_samples, 2)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_property_min_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        def _create_events_for_user(variant: str, amounts: list[int]) -> list[dict]:
            purchase_events = [
                {
                    "event": "purchase",
                    "timestamp": f"2024-01-02T12:01:{i:02d}",
                    "properties": {
                        ff_property: variant,
                        "amount": amount,
                    },
                }
                for i, amount in enumerate(amounts)
            ]
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
                *purchase_events,
            ]

        journeys_for(
            {
                "control_1": _create_events_for_user("control", [10, 20, 30]),
                "control_2": _create_events_for_user("control", [5, 15, 25]),
                "test_1": _create_events_for_user("test", [50, 60, 70]),
                "test_2": _create_events_for_user("test", [40, 80, 90]),
            },
            self.team,
        )

        flush_persons_and_events()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.MIN,
                math_property="amount",
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

        self.assertEqual(control_variant.sum, 15)
        self.assertEqual(test_variant.sum, 90)
        self.assertEqual(control_variant.number_of_samples, 2)
        self.assertEqual(test_variant.number_of_samples, 2)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_property_avg_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        def _create_events_for_user(variant: str, amounts: list[int]) -> list[dict]:
            purchase_events = [
                {
                    "event": "purchase",
                    "timestamp": f"2024-01-02T12:01:{i:02d}",
                    "properties": {
                        ff_property: variant,
                        "amount": amount,
                    },
                }
                for i, amount in enumerate(amounts)
            ]
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
                *purchase_events,
            ]

        journeys_for(
            {
                "control_1": _create_events_for_user("control", [10, 20, 30]),
                "control_2": _create_events_for_user("control", [5, 15, 25]),
                "test_1": _create_events_for_user("test", [50, 60, 70]),
                "test_2": _create_events_for_user("test", [40, 80, 90]),
            },
            self.team,
        )

        flush_persons_and_events()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.AVG,
                math_property="amount",
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

        self.assertEqual(control_variant.sum, 35)
        self.assertEqual(test_variant.sum, 130)
        self.assertEqual(control_variant.number_of_samples, 2)
        self.assertEqual(test_variant.number_of_samples, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_outlier_handling_with_ignore_zeros(self):
        """Test that ignore_zeros works correctly when calculating upper bound percentile"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        # Create metric with outlier handling and ignore_zeros enabled
        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            upper_bound_percentile=0.9,  # 90th percentile
            ignore_zeros=True,  # This should exclude zeros from percentile calculation
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Create events with a mix of zeros and non-zero values
        # Control: 5 users with 0, 3 users with 100, 2 users with 1000 (outliers)
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
            # First 5 users have 0 amount (should be ignored in percentile calculation)
            if i < 5:
                amount = 0
            elif i < 8:
                amount = 100
            else:
                amount = 1000  # Outliers that should be capped

            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "control", "amount": amount},
            )

        # Test: Similar distribution
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
            # First 5 users have 0 amount
            if i < 5:
                amount = 0
            elif i < 8:
                amount = 150
            else:
                amount = 2000  # Outliers that should be capped

            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "test", "amount": amount},
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # With ignore_zeros=True, the 90th percentile should be calculated from non-zero values only
        # For control: [100, 100, 100, 1000, 1000] -> 90th percentile = 1000, so outliers aren't capped
        # For test: [150, 150, 150, 2000, 2000] -> 90th percentile = 2000, so outliers aren't capped
        # But if zeros were included, percentiles would be much lower and outliers would be capped

        # All users are included in the sample count
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)

        # With ignore_zeros=True and 90th percentile:
        # For control: non-zero values are [100, 100, 100, 1000, 1000] -> 90th percentile = 1000
        # For test: non-zero values are [150, 150, 150, 2000, 2000] -> 90th percentile = 2000
        # Since the 90th percentile equals the max outlier values, they should not be capped

        # Control: 5*0 + 3*100 + 2*1000 = 2300
        # Test: 5*0 + 3*150 + 2*2000 = 4450
        self.assertEqual(control_variant.sum, 2300)
        self.assertEqual(test_variant.sum, 4450)
