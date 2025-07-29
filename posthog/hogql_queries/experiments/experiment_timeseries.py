import logging
from typing import Union
from datetime import datetime

from posthog.models import Experiment
from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.experiments.exposure_query_logic import (
    get_multiple_variant_handling_from_experiment,
    get_entity_key,
)
from posthog.hogql_queries.experiments.base_query_utils import (
    get_experiment_date_range,
    get_experiment_exposure_query,
    get_metric_events_query,
    get_metric_aggregation_expr,
    get_winsorized_metric_values_query,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.schema import (
    IntervalType,
    ExperimentMeanMetric,
    ExperimentFunnelMetric,
    ExperimentDataWarehouseNode,
    ExperimentStatsBase,
)

logger = logging.getLogger(__name__)


class ExperimentTimeseries:
    def __init__(self, experiment: Experiment, metric: Union[ExperimentFunnelMetric, ExperimentMeanMetric]):
        """Initialize the ExperimentTimeseries with an Experiment and metric objects"""
        self.experiment = experiment
        self.feature_flag = experiment.feature_flag
        self.team = experiment.team
        self.metric = metric

        self.group_type_index = self.feature_flag.filters.get("aggregation_group_type_index")
        self.entity_key = get_entity_key(self.group_type_index)
        self.variants = [variant["key"] for variant in self.feature_flag.variants]
        if self.experiment.holdout:
            self.variants.append(f"holdout-{self.experiment.holdout.id}")

        self.date_range = get_experiment_date_range(self.experiment, self.team)
        self.date_range_query = QueryDateRange(
            date_range=self.date_range,
            team=self.team,
            interval=IntervalType.DAY,
            now=datetime.now(),
        )

        self.multiple_variant_handling = get_multiple_variant_handling_from_experiment(self.experiment)

        self.is_data_warehouse_query = isinstance(self.metric, ExperimentMeanMetric) and isinstance(
            self.metric.source, ExperimentDataWarehouseNode
        )

    def _get_daily_exposure_counts_query(self, exposure_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Counts how many users were first exposed to each variant on each day.

        INPUT (exposure_query): One row per user with their first exposure
        | entity_id | variant | first_exposure_time     |
        |-----------|---------|-------------------------|
        | user_1    | control | 2025-05-27 14:30:00     |
        | user_2    | control | 2025-05-27 16:45:00     |
        | user_3    | test-1  | 2025-05-28 09:15:00     |

        OUTPUT: One row per variant per day (counts of new exposures)
        | variant | date       | daily_new_users |
        |---------|------------|-----------------|
        | control | 2025-05-27 | 2               |
        | test-1  | 2025-05-28 | 1               |
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["exposures", "variant"]),
                ast.Alias(
                    alias="date",
                    expr=ast.Call(
                        name="toStartOfDay",
                        args=[ast.Field(chain=["exposures", "first_exposure_time"])],
                    ),
                ),
                ast.Alias(
                    alias="daily_new_users",
                    expr=ast.Call(
                        name="count",
                        args=[ast.Constant(value=1)],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=exposure_query, alias="exposures"),
            group_by=[
                ast.Field(chain=["exposures", "variant"]),
                ast.Call(
                    name="toStartOfDay",
                    args=[ast.Field(chain=["exposures", "first_exposure_time"])],
                ),
            ],
        )

    def _get_daily_entity_metrics_from_exposed_users_query(
        self, metric_events_query: ast.SelectQuery
    ) -> ast.SelectQuery:
        """
        Aggregates each user's metric events by day (for users who were exposed to the experiment).

        INPUT (metric_events_query): One row per metric event from exposed users
        | variant | entity_id | timestamp           | value |
        |---------|-----------|---------------------|-------|
        | control | user_1    | 2025-05-27 14:35:00 | 1     |
        | control | user_1    | 2025-05-27 18:20:00 | 1     |
        | control | user_2    | 2025-05-28 10:15:00 | 1     |
        | test-1  | user_3    | 2025-05-27 12:30:00 | 1     |

        OUTPUT: One row per user per day (aggregated metric values)
        | variant | entity_id | date       | value |
        |---------|-----------|------------|-------|
        | control | user_1    | 2025-05-27 | 2     |
        | control | user_2    | 2025-05-28 | 1     |
        | test-1  | user_3    | 2025-05-27 | 1     |
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["metric_events", "variant"]),
                ast.Field(chain=["metric_events", "entity_id"])
                if not self.is_data_warehouse_query
                else ast.Field(chain=["metric_events", "entity_identifier"]),
                ast.Alias(
                    alias="date",
                    expr=ast.Call(
                        name="toStartOfDay",
                        args=[ast.Field(chain=["metric_events", "timestamp"])],
                    ),
                ),
                ast.Alias(
                    expr=get_metric_aggregation_expr(self.experiment, self.metric, self.team),
                    alias="value",
                ),
            ],
            select_from=ast.JoinExpr(table=metric_events_query, alias="metric_events"),
            group_by=[
                ast.Field(chain=["metric_events", "variant"]),
                ast.Field(chain=["metric_events", "entity_id"])
                if not self.is_data_warehouse_query
                else ast.Field(chain=["metric_events", "entity_identifier"]),
                ast.Call(
                    name="toStartOfDay",
                    args=[ast.Field(chain=["metric_events", "timestamp"])],
                ),
            ],
        )

    def _get_daily_metric_aggregations_query(self, daily_entity_metrics_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Rolls up individual user metrics to daily variant totals.

        INPUT (daily_entity_metrics_query): One row per user per day
        | variant | entity_id | date       | value |
        |---------|-----------|------------|-------|
        | control | user_1    | 2025-05-27 | 10    |
        | control | user_2    | 2025-05-27 | 15    |
        | test-1  | user_3    | 2025-05-27 | 8     |

        OUTPUT: One row per variant per day (summed across all users)
        | variant | date       | daily_metric_sum | daily_sum_of_squares |
        |---------|------------|------------------|----------------------|
        | control | 2025-05-27 | 25               | 325                  |
        | test-1  | 2025-05-27 | 8                | 64                   |
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["daily_metrics", "variant"]),
                ast.Field(chain=["daily_metrics", "date"]),
                ast.Alias(
                    alias="daily_metric_sum",
                    expr=ast.Call(
                        name="sum",
                        args=[ast.Field(chain=["daily_metrics", "value"])],
                    ),
                ),
                ast.Alias(
                    alias="daily_sum_of_squares",
                    expr=ast.Call(
                        name="sum",
                        args=[
                            ast.Call(
                                name="power",
                                args=[
                                    ast.Field(chain=["daily_metrics", "value"]),
                                    ast.Constant(value=2),
                                ],
                            )
                        ],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=daily_entity_metrics_query, alias="daily_metrics"),
            group_by=[
                ast.Field(chain=["daily_metrics", "variant"]),
                ast.Field(chain=["daily_metrics", "date"]),
            ],
        )

    def _get_combined_daily_query(
        self, daily_exposure_counts_query: ast.SelectQuery, daily_metric_aggregations_query: ast.SelectQuery
    ) -> ast.SelectQuery:
        """
        Combines daily user exposures with daily metric totals using FULL OUTER JOIN.

        INPUT Stream A (daily_exposure_counts_query): Daily new user counts
        | variant | date       | daily_new_users |
        |---------|------------|-----------------|
        | control | 2025-05-27 | 100             |
        | test-1  | 2025-05-27 | 95              |
        | control | 2025-05-28 | 120             |

        INPUT Stream B (daily_metric_aggregations_query): Daily metric totals
        | variant | date       | daily_metric_sum | daily_sum_of_squares |
        |---------|------------|------------------|----------------------|
        | control | 2025-05-27 | 25               | 325                  |
        | test-1  | 2025-05-27 | 18               | 198                  |
        | test-1  | 2025-05-28 | 30               | 450                  |

        OUTPUT: Combined daily data (coalesce handles missing values)
        | variant | date       | daily_new_users | daily_metric_sum | daily_sum_of_squares |
        |---------|------------|-----------------|------------------|----------------------|
        | control | 2025-05-27 | 100             | 25               | 325                  |
        | test-1  | 2025-05-27 | 95              | 18               | 198                  |
        | control | 2025-05-28 | 120             | 0                | 0                    |
        | test-1  | 2025-05-28 | 0               | 30               | 450                  |
        """
        return ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="variant",
                    expr=ast.Call(
                        name="coalesce",
                        args=[
                            ast.Field(chain=["exposures", "variant"]),
                            ast.Field(chain=["metrics", "variant"]),
                        ],
                    ),
                ),
                ast.Alias(
                    alias="date",
                    expr=ast.Call(
                        name="coalesce",
                        args=[
                            ast.Field(chain=["exposures", "date"]),
                            ast.Field(chain=["metrics", "date"]),
                        ],
                    ),
                ),
                ast.Alias(
                    alias="daily_new_users",
                    expr=ast.Call(
                        name="coalesce",
                        args=[
                            ast.Field(chain=["exposures", "daily_new_users"]),
                            ast.Constant(value=0),
                        ],
                    ),
                ),
                ast.Alias(
                    alias="daily_metric_sum",
                    expr=ast.Call(
                        name="coalesce",
                        args=[
                            ast.Field(chain=["metrics", "daily_metric_sum"]),
                            ast.Constant(value=0),
                        ],
                    ),
                ),
                ast.Alias(
                    alias="daily_sum_of_squares",
                    expr=ast.Call(
                        name="coalesce",
                        args=[
                            ast.Field(chain=["metrics", "daily_sum_of_squares"]),
                            ast.Constant(value=0),
                        ],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=daily_exposure_counts_query,
                alias="exposures",
                next_join=ast.JoinExpr(
                    table=daily_metric_aggregations_query,
                    join_type="FULL OUTER JOIN",
                    alias="metrics",
                    constraint=ast.JoinConstraint(
                        expr=ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    left=ast.Field(chain=["exposures", "variant"]),
                                    right=ast.Field(chain=["metrics", "variant"]),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                                ast.CompareOperation(
                                    left=ast.Field(chain=["exposures", "date"]),
                                    right=ast.Field(chain=["metrics", "date"]),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                            ]
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
        )

    def _get_cumulative_timeseries_query(self, combined_daily_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Applies window functions to create cumulative running totals over time.

        INPUT (combined_daily_query): Daily values for each variant
        | variant | date       | daily_new_users | daily_metric_sum | daily_sum_of_squares |
        |---------|------------|-----------------|------------------|----------------------|
        | control | 2025-05-27 | 100             | 25               | 325                  |
        | control | 2025-05-28 | 120             | 15               | 150                  |
        | test-1  | 2025-05-27 | 95              | 30               | 450                  |
        | test-1  | 2025-05-28 | 110             | 20               | 200                  |

        OUTPUT: Cumulative totals (window functions sum over date order)
        | variant | date       | num_users | total_sum | total_sum_of_squares |
        |---------|------------|-----------|-----------|----------------------|
        | control | 2025-05-27 | 100       | 25        | 325                  |
        | control | 2025-05-28 | 220       | 40        | 475                  |
        | test-1  | 2025-05-27 | 95        | 30        | 450                  |
        | test-1  | 2025-05-28 | 205       | 50        | 650                  |
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["combined_daily", "variant"]),
                ast.Field(chain=["combined_daily", "date"]),
                ast.Alias(
                    alias="num_users",
                    expr=ast.WindowFunction(
                        name="sum",
                        args=[ast.Field(chain=["combined_daily", "daily_new_users"])],
                        over_expr=ast.WindowExpr(
                            partition_by=[ast.Field(chain=["combined_daily", "variant"])],
                            order_by=[ast.OrderExpr(expr=ast.Field(chain=["combined_daily", "date"]))],
                            frame_method="ROWS",
                            frame_start=ast.WindowFrameExpr(
                                frame_type="PRECEDING",
                                frame_value=None,
                            ),
                            frame_end=ast.WindowFrameExpr(
                                frame_type="CURRENT ROW",
                                frame_value=None,
                            ),
                        ),
                    ),
                ),
                ast.Alias(
                    alias="total_sum",
                    expr=ast.WindowFunction(
                        name="sum",
                        args=[ast.Field(chain=["combined_daily", "daily_metric_sum"])],
                        over_expr=ast.WindowExpr(
                            partition_by=[ast.Field(chain=["combined_daily", "variant"])],
                            order_by=[ast.OrderExpr(expr=ast.Field(chain=["combined_daily", "date"]))],
                            frame_method="ROWS",
                            frame_start=ast.WindowFrameExpr(
                                frame_type="PRECEDING",
                                frame_value=None,
                            ),
                            frame_end=ast.WindowFrameExpr(
                                frame_type="CURRENT ROW",
                                frame_value=None,
                            ),
                        ),
                    ),
                ),
                ast.Alias(
                    alias="total_sum_of_squares",
                    expr=ast.WindowFunction(
                        name="sum",
                        args=[ast.Field(chain=["combined_daily", "daily_sum_of_squares"])],
                        over_expr=ast.WindowExpr(
                            partition_by=[ast.Field(chain=["combined_daily", "variant"])],
                            order_by=[ast.OrderExpr(expr=ast.Field(chain=["combined_daily", "date"]))],
                            frame_method="ROWS",
                            frame_start=ast.WindowFrameExpr(
                                frame_type="PRECEDING",
                                frame_value=None,
                            ),
                            frame_end=ast.WindowFrameExpr(
                                frame_type="CURRENT ROW",
                                frame_value=None,
                            ),
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=combined_daily_query, alias="combined_daily"),
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["combined_daily", "variant"])),
                ast.OrderExpr(expr=ast.Field(chain=["combined_daily", "date"])),
            ],
        )

    def _get_experiment_timeseries_query(self) -> ast.SelectQuery:
        """
        FLOW:
        1. Get exposures → daily exposure counts (by exposure date)
        2. Get metric events → daily entity metrics → daily totals (by event date)
        3. Combine both streams with FULL OUTER JOIN
        4. Apply window functions for cumulative totals

        FINAL OUTPUT: Cumulative experiment results over time
        | variant | date       | num_users | total_sum | total_sum_of_squares |
        |---------|------------|-----------|-----------|----------------------|
        | control | 2025-05-27 | 100       | 25        | 325                  |
        | control | 2025-05-28 | 220       | 40        | 475                  |
        | test-1  | 2025-05-27 | 95        | 30        | 450                  |
        | test-1  | 2025-05-28 | 205       | 50        | 650                  |
        """

        exposure_query = get_experiment_exposure_query(
            self.experiment,
            self.feature_flag,
            self.variants,
            self.date_range_query,
            self.team,
            self.entity_key,
            self.metric,
            self.multiple_variant_handling,
        )

        metric_events_query = get_metric_events_query(
            self.metric,
            exposure_query,
            self.team,
            self.entity_key,
            self.experiment,
            self.date_range_query,
        )

        # Stream A: Get daily user exposure counts (based on first_exposure_time)
        daily_exposure_counts_query = self._get_daily_exposure_counts_query(exposure_query)

        # Stream B: Get daily metric aggregations from exposed users
        daily_entity_metrics_query = self._get_daily_entity_metrics_from_exposed_users_query(metric_events_query)

        # Winsorize if needed
        if isinstance(self.metric, ExperimentMeanMetric) and (
            self.metric.lower_bound_percentile or self.metric.upper_bound_percentile
        ):
            daily_entity_metrics_query = get_winsorized_metric_values_query(self.metric, daily_entity_metrics_query)

        daily_metric_aggregations_query = self._get_daily_metric_aggregations_query(daily_entity_metrics_query)

        combined_daily_query = self._get_combined_daily_query(
            daily_exposure_counts_query, daily_metric_aggregations_query
        )

        return self._get_cumulative_timeseries_query(combined_daily_query)

    def _transform_timeseries_results(self, results: list[tuple]) -> list[dict]:
        """
        Transform raw query results:
        [
            {
                "date": "2025-07-15T00:00:00Z",
                "variant_results": [
                    {
                        "key": "control",
                        "number_of_samples": 1000,
                        "sum": 226537017.70000008,
                        "sum_squares": 567352528220837.6
                    },
                    ...
                ]
            },
            ...
        ]
        """

        grouped_by_date: dict[str, list[dict[str, Union[str, int, float]]]] = {}
        for variant, date, num_users, total_sum, total_sum_of_squares in results:
            date_str = f"{date.isoformat()}T00:00:00Z"
            if date_str not in grouped_by_date:
                grouped_by_date[date_str] = []

            grouped_by_date[date_str].append(
                {
                    "key": variant,
                    "number_of_samples": num_users,
                    "sum": total_sum,
                    "sum_squares": total_sum_of_squares,
                }
            )

        return [
            {"date": date_str, "variant_results": variant_data}
            for date_str, variant_data in sorted(grouped_by_date.items())
        ]

    def _create_experiment_stats_base(
        self, variant: str, num_users: int, total_sum: float, total_sum_of_squares: float
    ) -> ExperimentStatsBase:
        """Create an ExperimentStatsBase object for a variant's daily results"""
        return ExperimentStatsBase(
            key=variant,
            number_of_samples=num_users,
            sum=total_sum,
            sum_squares=total_sum_of_squares,
        )

    def get_result(self) -> list[dict]:
        """
        Get the experiment timeseries results.

        Returns:
            list[dict]: Transformed timeseries results with format:
                [
                    {
                        "date": "2025-07-15T00:00:00Z",
                        "variant_results": [
                            {
                                "key": "control",
                                "number_of_samples": 1000,
                                "sum": 226537017.70000008,
                                "sum_squares": 567352528220837.6
                            },
                            ...
                        ]
                    },
                    ...
                ]
        """
        experiment_query = self._get_experiment_timeseries_query()

        timings = HogQLTimings()
        response = execute_hogql_query(
            query_type="ExperimentQuery",
            query=experiment_query,
            team=self.team,
            timings=timings,
            modifiers=create_default_modifiers_for_team(self.team),
            settings=HogQLGlobalSettings(max_execution_time=180),
        )

        return self._transform_timeseries_results(response.results)
