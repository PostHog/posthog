from typing import cast

import pytest
from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    ActionsNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
    FunnelConversionWindowTimeUnit,
)

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from posthog.models.action.action import Action
from posthog.test.test_journeys import journeys_for


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentRatioMetric(ExperimentQueryRunnerBaseTest):
    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_basic_ratio_metric(self, name, use_new_query_builder):
        """Test basic ratio metric functionality with revenue per purchase event"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        # Create a ratio metric: total revenue / total purchase events
        metric = ExperimentRatioMetric(
            numerator=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            denominator=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.TOTAL,
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group: 10 visitors, 6 make purchases with varying amounts
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

            # First 6 users make purchases
            if i < 6:
                # Some users make multiple purchases to test aggregation
                if i < 3:
                    # Users 0,1,2 make single purchases of $10 each
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_control_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: "control", "amount": 10},
                    )
                else:
                    # Users 3,4,5 make two purchases each of $15
                    for j in range(2):
                        _create_event(
                            team=self.team,
                            event="purchase",
                            distinct_id=f"user_control_{i}",
                            timestamp=f"2020-01-02T12:0{j+1}:00Z",
                            properties={feature_flag_property: "control", "amount": 15},
                        )

        # Test group: 10 visitors, 8 make purchases with varying amounts
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

            # First 8 users make purchases
            if i < 8:
                if i < 4:
                    # Users 0,1,2,3 make single purchases of $20 each
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_test_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: "test", "amount": 20},
                    )
                else:
                    # Users 4,5,6,7 make two purchases each of $10
                    for j in range(2):
                        _create_event(
                            team=self.team,
                            event="purchase",
                            distinct_id=f"user_test_{i}",
                            timestamp=f"2020-01-02T12:0{j+1}:00Z",
                            properties={feature_flag_property: "test", "amount": 10},
                        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # Check main metric values (numerator - total revenue)
        self.assertEqual(control_variant.sum, 120)  # 3×$10 + 6×$15 = $30 + $90 = $120
        self.assertEqual(test_variant.sum, 160)  # 4×$20 + 8×$10 = $80 + $80 = $160
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)

        # Check ratio-specific fields (denominator - total purchase events)
        self.assertEqual(control_variant.denominator_sum, 9)  # 3 + 6 = 9 purchase events
        self.assertEqual(test_variant.denominator_sum, 12)  # 4 + 8 = 12 purchase events

        # Check denominator sum squares and main-denominator sum product exist
        # (specific values depend on how purchase events are aggregated per user)
        self.assertIsNotNone(control_variant.denominator_sum_squares)
        self.assertIsNotNone(test_variant.denominator_sum_squares)

        # Check main-denominator sum product
        self.assertIsNotNone(control_variant.numerator_denominator_sum_product)
        self.assertIsNotNone(test_variant.numerator_denominator_sum_product)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_ratio_metric_different_math_types(self, name, use_new_query_builder):
        """Test ratio metric with different math types for numerator and denominator"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create a ratio metric: average order value / unique sessions
        metric = ExperimentRatioMetric(
            numerator=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.AVG,
                math_property="amount",
            ),
            denominator=EventsNode(
                event="pageview",
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

        def _create_events_for_user(variant: str, session_id: str, purchase_amounts: list[int]) -> list[dict]:
            events = [
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
                {
                    "event": "pageview",
                    "timestamp": "2024-01-02T12:01:00",
                    "properties": {
                        ff_property: variant,
                        "$session_id": session_id,
                    },
                },
            ]

            # Add purchase events
            for i, amount in enumerate(purchase_amounts):
                events.append(
                    {
                        "event": "purchase",
                        "timestamp": f"2024-01-02T12:0{2+i}:00",
                        "properties": {
                            ff_property: variant,
                            "amount": amount,
                            "$session_id": session_id,
                        },
                    }
                )

            return events

        journeys_for(
            {
                # Control: 2 users, 2 sessions, average purchase amounts [20, 30] and [40]
                "control_1": _create_events_for_user("control", "session_c1", [20, 30]),
                "control_2": _create_events_for_user("control", "session_c2", [40]),
                # Test: 2 users, 2 sessions, average purchase amounts [50, 60] and [80]
                "test_1": _create_events_for_user("test", "session_t1", [50, 60]),
                "test_2": _create_events_for_user("test", "session_t2", [80]),
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

        # Control: avg([25, 40]) = 32.5 (numerator), 2 unique sessions (denominator)
        self.assertEqual(control_variant.sum, 65)  # 25 + 40 = 65 (sum for avg calculation)
        self.assertEqual(control_variant.number_of_samples, 2)
        self.assertEqual(control_variant.denominator_sum, 2)  # 2 unique sessions

        # Test: avg([55, 80]) = 67.5 (numerator), 2 unique sessions (denominator)
        self.assertEqual(test_variant.sum, 135)  # 55 + 80 = 135 (sum for avg calculation)
        self.assertEqual(test_variant.number_of_samples, 2)
        self.assertEqual(test_variant.denominator_sum, 2)  # 2 unique sessions

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_ratio_metric_with_conversion_window(self, name, use_new_query_builder):
        """Test ratio metric with conversion window"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create a ratio metric with 1-hour conversion window
        metric = ExperimentRatioMetric(
            numerator=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            denominator=EventsNode(
                event="pageview",
                math=ExperimentMetricMathType.TOTAL,
            ),
            conversion_window=1,
            conversion_window_unit=FunnelConversionWindowTimeUnit.HOUR,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        def _create_events_for_user(variant: str, within_window: bool) -> list[dict]:
            # Events within or outside conversion window
            purchase_timestamp = (
                "2024-01-02T12:30:00" if within_window else "2024-01-02T14:00:00"
            )  # 30min vs 2h after exposure
            pageview_timestamp = (
                "2024-01-02T12:15:00" if within_window else "2024-01-02T13:30:00"
            )  # 15min vs 1.5h after exposure

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
                    "event": "pageview",
                    "timestamp": pageview_timestamp,
                    "properties": {
                        ff_property: variant,
                    },
                },
                {
                    "event": "purchase",
                    "timestamp": purchase_timestamp,
                    "properties": {
                        ff_property: variant,
                        "amount": 100,
                    },
                },
            ]

        journeys_for(
            {
                # Control: 2 users within window, 1 user outside window
                "control_1": _create_events_for_user("control", within_window=True),
                "control_2": _create_events_for_user("control", within_window=True),
                "control_3": _create_events_for_user("control", within_window=False),  # Should be excluded
                # Test: 3 users within window
                "test_1": _create_events_for_user("test", within_window=True),
                "test_2": _create_events_for_user("test", within_window=True),
                "test_3": _create_events_for_user("test", within_window=True),
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

        # Control: 2 purchases within window ($200), 2 pageviews within window
        self.assertEqual(control_variant.sum, 200)
        self.assertEqual(control_variant.number_of_samples, 3)  # All users are exposed
        self.assertEqual(control_variant.denominator_sum, 2)  # Only 2 pageviews within window

        # Test: 3 purchases within window ($300), 3 pageviews within window
        self.assertEqual(test_variant.sum, 300)
        self.assertEqual(test_variant.number_of_samples, 3)
        self.assertEqual(test_variant.denominator_sum, 3)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_ratio_metric_zero_denominator(self, name, use_new_query_builder):
        """Test ratio metric behavior when denominator is zero"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create a ratio metric where denominator events don't exist for control
        metric = ExperimentRatioMetric(
            numerator=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            denominator=EventsNode(
                event="special_event",  # Only test group will have this event
                math=ExperimentMetricMathType.TOTAL,
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        def _create_events_for_user(variant: str, include_special_event: bool = True) -> list[dict]:
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
                    "event": "purchase",
                    "timestamp": "2024-01-02T12:01:00",
                    "properties": {
                        ff_property: variant,
                        "amount": 50,
                    },
                },
            ]

            if include_special_event:
                events.append(
                    {
                        "event": "special_event",
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: variant,
                        },
                    }
                )

            return events

        journeys_for(
            {
                # Control: purchases but no special_events (denominator = 0)
                "control_1": _create_events_for_user("control", include_special_event=False),
                "control_2": _create_events_for_user("control", include_special_event=False),
                # Test: purchases and special_events
                "test_1": _create_events_for_user("test", include_special_event=True),
                "test_2": _create_events_for_user("test", include_special_event=True),
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

        # Control: purchases exist, but no denominator events
        self.assertEqual(control_variant.sum, 100)  # 2 * $50
        self.assertEqual(control_variant.number_of_samples, 2)
        self.assertEqual(control_variant.denominator_sum, 0)  # No special_events

        # Test: both numerator and denominator exist
        self.assertEqual(test_variant.sum, 100)  # 2 * $50
        self.assertEqual(test_variant.number_of_samples, 2)
        self.assertEqual(test_variant.denominator_sum, 2)  # 2 special_events

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_ratio_metric_same_event_different_properties(self, name, use_new_query_builder):
        """Test ratio metric using the same event with different math properties"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create a ratio metric: total revenue / total quantity (both from purchase events)
        metric = ExperimentRatioMetric(
            numerator=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="revenue",
            ),
            denominator=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="quantity",
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        def _create_events_for_user(variant: str, purchases: list[dict]) -> list[dict]:
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

            for i, purchase in enumerate(purchases):
                events.append(
                    {
                        "event": "purchase",
                        "timestamp": f"2024-01-02T12:0{i+1}:00",
                        "properties": {
                            ff_property: variant,
                            "revenue": purchase["revenue"],
                            "quantity": purchase["quantity"],
                        },
                    }
                )

            return events

        journeys_for(
            {
                # Control: Lower prices, higher quantities
                "control_1": _create_events_for_user(
                    "control",
                    [
                        {"revenue": 10, "quantity": 5},  # $2 per unit
                        {"revenue": 20, "quantity": 8},  # $2.5 per unit
                    ],
                ),
                "control_2": _create_events_for_user(
                    "control",
                    [
                        {"revenue": 30, "quantity": 10},  # $3 per unit
                    ],
                ),
                # Test: Higher prices, lower quantities
                "test_1": _create_events_for_user(
                    "test",
                    [
                        {"revenue": 50, "quantity": 5},  # $10 per unit
                        {"revenue": 60, "quantity": 6},  # $10 per unit
                    ],
                ),
                "test_2": _create_events_for_user(
                    "test",
                    [
                        {"revenue": 80, "quantity": 8},  # $10 per unit
                    ],
                ),
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

        # Control: total revenue = $60, total quantity = 23
        self.assertEqual(control_variant.sum, 60)  # 10 + 20 + 30
        self.assertEqual(control_variant.number_of_samples, 2)
        self.assertEqual(control_variant.denominator_sum, 23)  # 5 + 8 + 10

        # Test: total revenue = $190, total quantity = 19
        self.assertEqual(test_variant.sum, 190)  # 50 + 60 + 80
        self.assertEqual(test_variant.number_of_samples, 2)
        self.assertEqual(test_variant.denominator_sum, 19)  # 5 + 6 + 8

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_ratio_metric_action_and_event_sources(self, name, use_new_query_builder):
        """Test ratio metric with action source numerator and event source denominator"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create an action for purchase events
        purchase_action = Action.objects.create(
            name="Purchase Action", team=self.team, steps_json=[{"event": "purchase"}]
        )
        purchase_action.save()

        # Create a ratio metric: action-based purchase revenue / event-based page views
        # This demonstrates using ActionsNode vs EventsNode as different source types
        metric = ExperimentRatioMetric(
            numerator=ActionsNode(
                id=purchase_action.id,
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            denominator=EventsNode(
                event="pageview",
                math=ExperimentMetricMathType.TOTAL,
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        def _create_events_for_user(
            variant: str, user_id: str, purchase_amount: int, pageview_count: int
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

            # Add pageview events
            for i in range(pageview_count):
                events.append(
                    {
                        "event": "pageview",
                        "timestamp": f"2024-01-02T12:0{i+1}:00",
                        "properties": {
                            ff_property: variant,
                            "page": f"/page{i}",
                        },
                    }
                )

            # Add purchase event if amount > 0
            if purchase_amount > 0:
                events.append(
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02T12:05:00",
                        "properties": {
                            ff_property: variant,
                            "amount": purchase_amount,
                        },
                    }
                )

            return events

        journeys_for(
            {
                # Control: mixed behavior - some users purchase, all users view pages
                "control_1": _create_events_for_user("control", "user_control_1", 50, 2),  # $50, 2 pageviews
                "control_2": _create_events_for_user("control", "user_control_2", 0, 3),  # $0, 3 pageviews
                "control_3": _create_events_for_user("control", "user_control_3", 75, 1),  # $75, 1 pageview
                # Test: higher conversion and engagement
                "test_1": _create_events_for_user("test", "user_test_1", 100, 4),  # $100, 4 pageviews
                "test_2": _create_events_for_user("test", "user_test_2", 150, 2),  # $150, 2 pageviews
                "test_3": _create_events_for_user("test", "user_test_3", 0, 5),  # $0, 5 pageviews
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

        # Numerator: total purchase revenue (via Action)
        self.assertEqual(control_variant.sum, 125)  # $50 + $0 + $75 = $125
        self.assertEqual(test_variant.sum, 250)  # $100 + $150 + $0 = $250
        self.assertEqual(control_variant.number_of_samples, 3)
        self.assertEqual(test_variant.number_of_samples, 3)

        # Denominator: total pageviews (via EventsNode)
        self.assertEqual(control_variant.denominator_sum, 6)  # 2 + 3 + 1 = 6 pageviews
        self.assertEqual(test_variant.denominator_sum, 11)  # 4 + 2 + 5 = 11 pageviews

        # Check that ratio-specific fields exist
        self.assertIsNotNone(control_variant.denominator_sum_squares)
        self.assertIsNotNone(test_variant.denominator_sum_squares)
        self.assertIsNotNone(control_variant.numerator_denominator_sum_product)
        self.assertIsNotNone(test_variant.numerator_denominator_sum_product)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @snapshot_clickhouse_queries
    def test_ratio_metric_with_data_warehouse_sources(self, name, use_new_query_builder):
        """Test ratio metric with ExperimentDataWarehouseNode for both numerator and denominator"""
        from datetime import datetime

        table_name = self.create_data_warehouse_table_with_usage()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2023, 1, 1), end_date=datetime(2023, 1, 31)
        )
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Create a ratio metric using data warehouse for both numerator and denominator
        # This tests support for ExperimentDataWarehouseNode in ratio metrics
        metric = ExperimentRatioMetric(
            numerator=ExperimentDataWarehouseNode(
                table_name=table_name,
                events_join_key="properties.$user_id",
                data_warehouse_join_key="userid",
                timestamp_field="ds",
                math=ExperimentMetricMathType.SUM,
                math_property="usage",
            ),
            denominator=ExperimentDataWarehouseNode(
                table_name=table_name,
                events_join_key="properties.$user_id",
                data_warehouse_join_key="userid",
                timestamp_field="ds",
                math=ExperimentMetricMathType.TOTAL,
                math_property=None,
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.exposure_criteria = {"filterTestAccounts": False}
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Populate exposure events - these users correspond to data warehouse records
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"distinct_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                        "$user_id": f"user_{variant}_{i}",
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        with freeze_time("2023-01-07"):
            result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertIsNotNone(control_variant.sum)  # Numerator: sum of usage
        self.assertIsNotNone(test_variant.sum)
        self.assertTrue(control_variant.number_of_samples > 0)
        self.assertTrue(test_variant.number_of_samples > 0)

        self.assertIsNotNone(control_variant.denominator_sum)  # Denominator: count of records
        self.assertIsNotNone(test_variant.denominator_sum)

        # Check that ratio-specific statistical fields are populated
        self.assertIsNotNone(control_variant.denominator_sum_squares)
        self.assertIsNotNone(test_variant.denominator_sum_squares)
        self.assertIsNotNone(control_variant.numerator_denominator_sum_product)
        self.assertIsNotNone(test_variant.numerator_denominator_sum_product)

    # TODO: This is skipped as SQL expressions in ratio metrics are not supported yet
    # We need to handle aggregations differently there compared to what we do i mean metrics.
    @pytest.mark.skip
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_ratio_metric_with_hogql_math_type(self):
        """Test ratio metric with revenue per distinct user id with hogql expression"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        # Create a ratio metric: total revenue / total purchase events
        metric = ExperimentRatioMetric(
            numerator=EventsNode(
                event="purchase", math=ExperimentMetricMathType.HOGQL, math_hogql="sum(toFloat(properties.amount))"
            ),
            denominator=EventsNode(
                event="purchase", math=ExperimentMetricMathType.HOGQL, math_hogql="uniqExact(distinct_id)"
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control group: 10 visitors, 6 make purchases with varying amounts
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

            # First 6 users make purchases
            if i < 6:
                # Some users make multiple purchases to test aggregation
                if i < 3:
                    # Users 0,1,2 make single purchases of $10 each
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_control_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: "control", "amount": 10},
                    )
                else:
                    # Users 3,4,5 make two purchases each of $15
                    for j in range(2):
                        _create_event(
                            team=self.team,
                            event="purchase",
                            distinct_id=f"user_control_{i}",
                            timestamp=f"2020-01-02T12:0{j+1}:00Z",
                            properties={feature_flag_property: "control", "amount": 15},
                        )

        # Test group: 10 visitors, 8 make purchases with varying amounts
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

            # First 8 users make purchases
            if i < 8:
                if i < 4:
                    # Users 0,1,2,3 make single purchases of $20 each
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_test_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: "test", "amount": 20},
                    )
                else:
                    # Users 4,5,6,7 make two purchases each of $10
                    for j in range(2):
                        _create_event(
                            team=self.team,
                            event="purchase",
                            distinct_id=f"user_test_{i}",
                            timestamp=f"2020-01-02T12:0{j+1}:00Z",
                            properties={feature_flag_property: "test", "amount": 10},
                        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # Check main metric values (numerator - total revenue)
        self.assertEqual(control_variant.sum, 120)  # 3×$10 + 6×$15 = $30 + $90 = $120
        self.assertEqual(test_variant.sum, 160)  # 4×$20 + 8×$10 = $80 + $80 = $160
        self.assertEqual(control_variant.number_of_samples, 10)  # 10 visitors in total
        self.assertEqual(test_variant.number_of_samples, 10)  # 10 visitors in total

        # Check ratio-specific fields (denominator - number of distinct user id's)
        self.assertEqual(control_variant.denominator_sum, 6)  # 6 distinct users make a purchase
        self.assertEqual(test_variant.denominator_sum, 8)  # 8 distinct users make a purchase

        # Check denominator sum squares and main-denominator sum product exist
        # (specific values depend on how purchase events are aggregated per user)
        self.assertIsNotNone(control_variant.denominator_sum_squares)
        self.assertIsNotNone(test_variant.denominator_sum_squares)

        # Check main-denominator sum product
        self.assertIsNotNone(control_variant.numerator_denominator_sum_product)
        self.assertIsNotNone(test_variant.numerator_denominator_sum_product)
