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
    EventsNode,
    ExperimentStatsBase,
)

logger = logging.getLogger(__name__)


class ExperimentTimeseries:
    def __init__(self, experiment: Experiment):
        """Initialize the ExperimentTimeseries with an Experiment object"""
        self.experiment = experiment
        self.feature_flag = experiment.feature_flag
        self.team = experiment.team

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

        # Get the first metric and parse it
        self.metric: Union[ExperimentFunnelMetric, ExperimentMeanMetric]
        if self.experiment.metrics:
            raw_metric = self.experiment.metrics[0]
            if raw_metric.get("metric_type") == "funnel":
                self.metric = ExperimentFunnelMetric(
                    series=[EventsNode(**step) for step in raw_metric["series"]],
                    conversion_window=raw_metric.get("conversion_window"),
                    conversion_window_unit=raw_metric.get("conversion_window_unit"),
                )
            else:
                series_data = raw_metric["series"][0] if raw_metric.get("series") else {}
                self.metric = ExperimentMeanMetric(
                    source=EventsNode(**series_data),
                    conversion_window=raw_metric.get("conversion_window"),
                    conversion_window_unit=raw_metric.get("conversion_window_unit"),
                )
        else:
            raise ValueError("No metrics found for this experiment")

        self.is_data_warehouse_query = isinstance(self.metric, ExperimentMeanMetric) and isinstance(
            self.metric.source, ExperimentDataWarehouseNode
        )

    # NEW FUNCTION: Get daily exposure counts based on first exposure date
    def _get_daily_exposure_counts_query(self, exposure_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Returns a query that counts users who were first exposed on each day
        Columns: variant, date, daily_new_users
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

    # CORRECTED FUNCTION: Get daily entity metrics from exposed users only
    def _get_daily_entity_metrics_from_exposed_users_query(
        self, exposure_query: ast.SelectQuery, metric_events_query: ast.SelectQuery
    ) -> ast.SelectQuery:
        """
        Returns daily metric values per entity from exposed users (simplified - no double join needed)
        metric_events_query already contains variant from exposure and is filtered to exposed users
        Columns: variant, entity_id, date, value
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["metric_events", "variant"]),  # Already from exposure data
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
                    expr=get_metric_aggregation_expr(self.metric, self.team),
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

    # NEW FUNCTION: Aggregate daily metrics by variant and date
    def _get_daily_metric_aggregations_query(self, daily_entity_metrics_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Aggregates entity+date metrics to variant+date level
        Columns: variant, date, daily_metric_sum, daily_sum_of_squares
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

    # NEW FUNCTION: Combine the two parallel data streams
    def _get_combined_daily_query(
        self, daily_exposure_counts_query: ast.SelectQuery, daily_metric_aggregations_query: ast.SelectQuery
    ) -> ast.SelectQuery:
        """
        Combines daily exposure counts with daily metric aggregations
        Columns: variant, date, daily_new_users, daily_metric_sum, daily_sum_of_squares
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

    # UPDATED FUNCTION: Apply cumulative calculations to combined daily data
    def _get_cumulative_timeseries_query(self, combined_daily_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Creates the final timeseries query with cumulative calculations using window functions
        Columns: variant, date, num_users, total_sum, total_sum_of_squares
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
        Creates a timeseries query that returns cumulative daily results for each variant
        Returns one row per (variant, date) combination with cumulative statistics
        Columns: variant, date, num_users, total_sum, total_sum_of_squares
        """
        # Get all entities that should be included in the experiment
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

        # Get all metric events from exposed users (maintaining the exposure connection)
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

        # Stream B: Get daily metric aggregations from exposed users (based on metric event timestamps)
        daily_entity_metrics_query = self._get_daily_entity_metrics_from_exposed_users_query(
            exposure_query, metric_events_query
        )

        # Winsorize if needed
        if isinstance(self.metric, ExperimentMeanMetric) and (
            self.metric.lower_bound_percentile or self.metric.upper_bound_percentile
        ):
            daily_entity_metrics_query = get_winsorized_metric_values_query(self.metric, daily_entity_metrics_query)

        # Aggregate entity+date metrics to variant+date level
        daily_metric_aggregations_query = self._get_daily_metric_aggregations_query(daily_entity_metrics_query)

        # Combine the two parallel streams
        combined_daily_query = self._get_combined_daily_query(
            daily_exposure_counts_query, daily_metric_aggregations_query
        )

        # Final timeseries query with cumulative calculations using window functions
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
