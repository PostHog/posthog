from datetime import datetime

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.analytics_platform.backend.lazy_computation.funnels_precomputation import (
    FunnelPrecomputationConfig,
    FunnelStep,
    build_funnel_hourly_combiner,
    build_funnel_hourly_sketches_insert,
    build_funnel_step_timestamps_insert,
)
from products.analytics_platform.backend.lazy_computation.retention_precomputation import (
    RetentionPrecomputationConfig,
    build_retention_combiner_query,
    build_retention_insert_query,
)
from products.analytics_platform.backend.lazy_computation.trends_precomputation import (
    TrendsPrecomputationConfig,
    build_trends_combiner_query,
    build_trends_insert_query,
    can_precompute_trends_series,
)


class TestTrendsPrecomputation(BaseTest):
    @parameterized.expand(
        [
            ("total", None, "sumState(toUInt64(1)) AS count_state"),
            ("dau", None, "uniqState(person_id) AS uniq_persons_state"),
            ("unique_session", None, "uniqState(events.`$session_id`) AS uniq_sessions_state"),
            ("sum", "$revenue", "sumState(toFloat64(events.properties.$revenue)) AS sum_state"),
            ("min", "$price", "minState(toFloat64(events.properties.$price)) AS min_state"),
            ("max", "$price", "maxState(toFloat64(events.properties.$price)) AS max_state"),
        ]
    )
    def test_insert_query_uses_correct_aggregate_function(self, math_type, math_property, expected_fragment):
        config = TrendsPrecomputationConfig(
            event="$pageview",
            math_type=math_type,
            math_property=math_property,
        )
        query = build_trends_insert_query(config)

        assert expected_fragment in query
        assert "toStartOfHour(timestamp) AS time_window_start" in query
        assert "event = '$pageview'" in query
        assert "{time_window_min}" in query
        assert "{time_window_max}" in query

    def test_insert_query_avg_produces_both_sum_and_count(self):
        config = TrendsPrecomputationConfig(
            event="purchase",
            math_type="avg",
            math_property="$amount",
        )
        query = build_trends_insert_query(config)

        assert "sumState(toFloat64(events.properties.$amount)) AS sum_state" in query
        assert "sumState(toUInt64(1)) AS count_state" in query

    def test_insert_query_with_breakdown(self):
        config = TrendsPrecomputationConfig(
            event="$pageview",
            math_type="total",
            breakdown_expr="properties.$browser",
        )
        query = build_trends_insert_query(config)

        assert "[toString(properties.$browser)] AS breakdown_value" in query
        assert "GROUP BY time_window_start, event, breakdown_value" in query

    def test_insert_query_without_breakdown(self):
        config = TrendsPrecomputationConfig(
            event="$pageview",
            math_type="total",
        )
        query = build_trends_insert_query(config)

        assert "[] AS breakdown_value" in query
        assert "breakdown_value" not in query.split("GROUP BY")[1]

    @parameterized.expand(
        [
            ("hour", "toStartOfHour(time_window_start)"),
            ("day", "toStartOfDay(time_window_start)"),
            ("week", "toStartOfWeek(time_window_start, 0)"),
            ("month", "toStartOfMonth(time_window_start)"),
        ]
    )
    def test_combiner_query_uses_correct_rollup_function(self, interval, expected_rollup):
        config = TrendsPrecomputationConfig(event="$pageview", math_type="total")
        query, _ = build_trends_combiner_query(
            config,
            interval=interval,
            time_start=datetime(2024, 1, 1),
            time_end=datetime(2024, 2, 1),
        )

        assert f"{expected_rollup} AS interval_start" in query

    @parameterized.expand(
        [
            ("total", "sumMerge(count_state)"),
            ("dau", "uniqMerge(uniq_persons_state)"),
            ("sum", "sumMerge(sum_state)"),
            ("avg", "sumMerge(sum_state) / sumMerge(count_state)"),
        ]
    )
    def test_combiner_query_uses_correct_merge_function(self, math_type, expected_merge):
        config = TrendsPrecomputationConfig(
            event="$pageview",
            math_type=math_type,
            math_property="$revenue" if math_type in ("sum", "avg") else None,
        )
        query, _ = build_trends_combiner_query(
            config,
            interval="day",
            time_start=datetime(2024, 1, 1),
            time_end=datetime(2024, 2, 1),
        )

        assert expected_merge in query

    def test_unsupported_math_type_raises(self):
        config = TrendsPrecomputationConfig(event="$pageview", math_type="median")
        with self.assertRaises(ValueError):
            build_trends_insert_query(config)

    @parameterized.expand(
        [
            ("total", True),
            ("dau", True),
            ("sum", True),
            ("avg", True),
            ("min", True),
            ("max", True),
            ("unique_session", True),
            ("median", False),
            ("p90", False),
            ("weekly_active", False),
            ("first_time_for_user", False),
            ("avg_count_per_actor", False),
        ]
    )
    def test_can_precompute_trends_series(self, math_type, expected):
        assert can_precompute_trends_series(math_type) == expected

    def test_none_math_type_defaults_to_total(self):
        assert can_precompute_trends_series(None) is True


class TestRetentionPrecomputation(BaseTest):
    def test_insert_query_same_event(self):
        config = RetentionPrecomputationConfig(
            start_event="$pageview",
            return_event="$pageview",
        )
        query = build_retention_insert_query(config)

        assert "event IN ('$pageview')" in query
        assert "uniqThetaState(person_id) AS uniq_theta_state" in query
        assert "toStartOfDay(timestamp) AS time_window_start" in query

    def test_insert_query_different_events(self):
        config = RetentionPrecomputationConfig(
            start_event="$pageview",
            return_event="purchase",
        )
        query = build_retention_insert_query(config)

        assert "'$pageview'" in query
        assert "'purchase'" in query

    def test_insert_query_weekly_interval(self):
        config = RetentionPrecomputationConfig(
            start_event="$pageview",
            return_event="$pageview",
            interval="week",
        )
        query = build_retention_insert_query(config)

        assert "toStartOfWeek(timestamp) AS time_window_start" in query

    def test_combiner_query_has_intersection(self):
        config = RetentionPrecomputationConfig(
            start_event="$pageview",
            return_event="$pageview",
        )
        query = build_retention_combiner_query(
            config,
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 1, 8),
            total_intervals=7,
        )

        assert "bitmapAndCardinality" in query
        assert "cohort_sketches" in query
        assert "return_sketches" in query
        assert "r.period >= c.period" in query
        assert "intervals_from_base" in query

    def test_combiner_query_different_events_filter_correctly(self):
        config = RetentionPrecomputationConfig(
            start_event="signup",
            return_event="purchase",
        )
        query = build_retention_combiner_query(
            config,
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 2, 1),
            total_intervals=31,
        )

        assert "event = 'signup'" in query
        assert "event = 'purchase'" in query


class TestFunnelsPrecomputation(BaseTest):
    def test_step_timestamps_insert_includes_all_events(self):
        config = FunnelPrecomputationConfig(
            steps=[
                FunnelStep(event="signup"),
                FunnelStep(event="onboarding"),
                FunnelStep(event="purchase"),
            ]
        )
        query = build_funnel_step_timestamps_insert(config)

        assert "'signup'" in query
        assert "'onboarding'" in query
        assert "'purchase'" in query
        assert "minState(toFloat64(toUnixTimestamp(timestamp))) AS min_state" in query
        assert "maxState(toFloat64(toUnixTimestamp(timestamp))) AS max_state" in query

    def test_hourly_sketches_insert_uses_theta(self):
        config = FunnelPrecomputationConfig(
            steps=[
                FunnelStep(event="view_product"),
                FunnelStep(event="add_to_cart"),
            ]
        )
        query = build_funnel_hourly_sketches_insert(config)

        assert "uniqThetaState(person_id) AS uniq_theta_state" in query
        assert "toStartOfHour(timestamp) AS time_window_start" in query
        assert "'view_product'" in query
        assert "'add_to_cart'" in query

    def test_hourly_combiner_two_step_funnel(self):
        config = FunnelPrecomputationConfig(
            steps=[
                FunnelStep(event="view_product"),
                FunnelStep(event="add_to_cart"),
            ],
            conversion_window_days=14,
        )
        query = build_funnel_hourly_combiner(config)

        assert "step_1_count" in query
        assert "step_2_count" in query
        assert "bitmapAndCardinality" in query
        assert "s2.period >= s1.period" in query
        assert "336" in query  # 14 * 24 hours

    def test_hourly_combiner_three_step_funnel(self):
        config = FunnelPrecomputationConfig(
            steps=[
                FunnelStep(event="view"),
                FunnelStep(event="cart"),
                FunnelStep(event="purchase"),
            ],
            conversion_window_days=7,
        )
        query = build_funnel_hourly_combiner(config)

        assert "step_1_total" in query
        assert "step_2_total" in query
        assert "step_3_total" in query
        assert "step1_to_2" in query  # intermediate intersection
        assert "168" in query  # 7 * 24 hours

    def test_hourly_combiner_rejects_single_step(self):
        config = FunnelPrecomputationConfig(steps=[FunnelStep(event="view")])
        with self.assertRaises(ValueError):
            build_funnel_hourly_combiner(config)

    def test_hourly_combiner_rejects_too_many_steps(self):
        config = FunnelPrecomputationConfig(
            steps=[FunnelStep(event=f"step_{i}") for i in range(4)],
        )
        with self.assertRaises(ValueError):
            build_funnel_hourly_combiner(config)


class TestPreaggregationV2TableSchema(BaseTest):
    """Verify the table SQL is well-formed."""

    def test_sharded_table_sql_is_valid(self):
        from posthog.clickhouse.preaggregation.preaggregation_v2_sql import SHARDED_TABLE_SQL

        sql = SHARDED_TABLE_SQL()
        assert "sharded_preaggregation_v2" in sql
        assert "AggregateFunction(uniq, UUID)" in sql
        assert "AggregateFunction(uniqTheta, UUID)" in sql
        assert "AggregateFunction(sum, UInt64)" in sql
        assert "AggregateFunction(sum, Float64)" in sql
        assert "AggregateFunction(min, Float64)" in sql
        assert "AggregateFunction(max, Float64)" in sql
        assert "event String" in sql
        assert "TTL expires_at" in sql

    def test_distributed_table_sql_is_valid(self):
        from posthog.clickhouse.preaggregation.preaggregation_v2_sql import DISTRIBUTED_TABLE_SQL

        sql = DISTRIBUTED_TABLE_SQL()
        assert "preaggregation_v2" in sql
        assert "sipHash64(job_id)" in sql
