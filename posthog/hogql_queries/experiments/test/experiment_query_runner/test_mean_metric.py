from typing import cast

from django.test import override_settings
from freezegun import freeze_time

from posthog.hogql_queries.experiments.experiment_query_runner import (
    ExperimentQueryRunner,
)
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import (
    ExperimentQueryRunnerBaseTest,
)
from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentVariantTrendsBaseStats,
    LegacyExperimentQueryResponse,
)
from posthog.test.base import (
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
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

        self.create_standard_test_events(feature_flag)

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 20)
        self.assertEqual(test_variant.count, 20)
        self.assertEqual(control_variant.absolute_exposure, 10)
        self.assertEqual(test_variant.absolute_exposure, 10)

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 1055)
        self.assertEqual(test_variant.count, 1055)
        self.assertEqual(control_variant.absolute_exposure, 10)
        self.assertEqual(test_variant.absolute_exposure, 10)

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
                "test_1": _create_events_for_user("test", 3),
                "test_2": _create_events_for_user("test", 3),
                "test_3": _create_events_for_user("test", 3),
                "test_4": _create_events_for_user("test", 3),
                "test_5": _create_events_for_user("test", 3),
                "test_6": _create_events_for_user("test", 3),
                "test_7": _create_events_for_user("test", 3),
                "test_8": _create_events_for_user("test", 3),
                "test_9": _create_events_for_user("test", 3),
                "test_10": _create_events_for_user("test", 3),
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 30)
        self.assertEqual(test_variant.count, 30)
        self.assertEqual(control_variant.absolute_exposure, 10)
        self.assertEqual(test_variant.absolute_exposure, 10)

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 3)
        self.assertEqual(test_variant.count, 5)
        self.assertEqual(control_variant.absolute_exposure, 2)
        self.assertEqual(test_variant.absolute_exposure, 2)

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 55)
        self.assertEqual(test_variant.count, 160)
        self.assertEqual(control_variant.absolute_exposure, 2)
        self.assertEqual(test_variant.absolute_exposure, 2)

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 15)
        self.assertEqual(test_variant.count, 90)
        self.assertEqual(control_variant.absolute_exposure, 2)
        self.assertEqual(test_variant.absolute_exposure, 2)

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 35)
        self.assertEqual(test_variant.count, 130)
        self.assertEqual(control_variant.absolute_exposure, 2)
        self.assertEqual(test_variant.absolute_exposure, 2)
