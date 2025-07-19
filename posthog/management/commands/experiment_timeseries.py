import logging
from typing import cast

from django.core.management.base import BaseCommand
from posthog.models import Experiment
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.experiments.exposure_query_logic import (
    get_exposure_event_and_property,
    build_common_exposure_conditions,
    get_variant_selection_expr,
    get_multiple_variant_handling_from_experiment,
    get_test_accounts_filter,
    get_entity_key,
)
from posthog.hogql_queries.experiments.base_query_utils import (
    get_data_warehouse_metric_source,
    get_metric_value,
    event_or_action_to_filter,
    conversion_window_to_seconds,
)
from posthog.hogql_queries.experiments.funnel_query_utils import (
    funnel_evaluation_expr,
    funnel_steps_to_filter,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.schema import (
    DateRange,
    IntervalType,
    ExperimentMeanMetric,
    ExperimentFunnelMetric,
    ExperimentDataWarehouseNode,
    EventsNode,
    ActionsNode,
    ExperimentMetricMathType,
    ExperimentStatsBase,
)
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch and print experiment with id=14"

    def add_arguments(self, parser):
        parser.add_argument(
            "--experiment-id",
            type=int,
            default=14,
            help="ID of the experiment to fetch (default: 14)",
        )

    # IDENTICAL TO EXPERIMENT QUERY RUNNER
    def _get_date_range(self) -> DateRange:
        """
        Returns an DateRange object based on the experiment's start and end dates,
        adjusted for the team's timezone if applicable.
        """

        if self.team.timezone:
            tz = ZoneInfo(self.team.timezone)
            start_date = self.experiment.start_date.astimezone(tz) if self.experiment.start_date else None
            end_date = self.experiment.end_date.astimezone(tz) if self.experiment.end_date else None
        else:
            start_date = self.experiment.start_date
            end_date = self.experiment.end_date

        return DateRange(
            date_from=start_date.isoformat() if start_date else None,
            date_to=end_date.isoformat() if end_date else None,
            explicitDate=True,
        )

    # IDENTICAL TO EXPERIMENT QUERY RUNNER
    def _get_metric_time_window(self, left: ast.Expr) -> list[ast.CompareOperation]:
        if self.metric.conversion_window is not None and self.metric.conversion_window_unit is not None:
            # Define conversion window as hours after exposure
            time_window_clause = ast.CompareOperation(
                left=left,
                right=ast.Call(
                    name="plus",
                    args=[
                        ast.Field(chain=["exposure_data", "first_exposure_time"]),
                        ast.Call(
                            name="toIntervalSecond",
                            args=[
                                ast.Constant(
                                    value=conversion_window_to_seconds(
                                        self.metric.conversion_window, self.metric.conversion_window_unit
                                    )
                                ),
                            ],
                        ),
                    ],
                ),
                op=ast.CompareOperationOp.Lt,
            )
        else:
            # If no conversion window, just limit to experiment end date
            time_window_clause = ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=left,
                right=ast.Constant(value=self.date_range_query.date_to()),
            )

        return [
            # Improve query performance by only fetching events after the experiment started
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=left,
                right=ast.Constant(value=self.date_range_query.date_from()),
            ),
            # Ensure the event occurred after the user was exposed to the experiment
            ast.CompareOperation(
                left=left,
                right=ast.Field(chain=["exposure_data", "first_exposure_time"]),
                op=ast.CompareOperationOp.GtEq,
            ),
            time_window_clause,
        ]

    # IDENTICAL TO EXPERIMENT QUERY RUNNER
    def _get_exposure_query(self) -> ast.SelectQuery:
        """
        Returns the query for the exposure data. One row per entity. If an entity is exposed to multiple variants,
        we place them in the $multiple variant so we can warn the user and exclude them from the analysis.
        Columns:
            entity_id
            variant
            first_exposure_time
        """

        event, feature_flag_variant_property = get_exposure_event_and_property(
            feature_flag_key=self.feature_flag.key, exposure_criteria=self.experiment.exposure_criteria
        )

        # Build common exposure conditions
        exposure_conditions = build_common_exposure_conditions(
            event=event,
            feature_flag_variant_property=feature_flag_variant_property,
            variants=self.variants,
            date_range_query=self.date_range_query,
            team=self.team,
            exposure_criteria=self.experiment.exposure_criteria,
            feature_flag_key=self.feature_flag.key,
        )

        exposure_query_select: list[ast.Expr] = [
            ast.Alias(alias="entity_id", expr=ast.Field(chain=[self.entity_key])),
            ast.Alias(
                alias="variant",
                expr=get_variant_selection_expr(feature_flag_variant_property, self.multiple_variant_handling),
            ),
            ast.Alias(
                alias="first_exposure_time",
                expr=ast.Call(
                    name="min",
                    args=[ast.Field(chain=["timestamp"])],
                ),
            ),
        ]
        exposure_query_group_by = [ast.Field(chain=["entity_id"])]
        if data_warehouse_metric_source := get_data_warehouse_metric_source(self.metric):
            exposure_query_select = [
                *exposure_query_select,
                ast.Alias(
                    alias="exposure_identifier",
                    expr=ast.Field(chain=[*data_warehouse_metric_source.events_join_key.split(".")]),
                ),
            ]
            exposure_query_group_by = [
                *exposure_query_group_by,
                ast.Field(chain=[*data_warehouse_metric_source.events_join_key.split(".")]),
            ]

        return ast.SelectQuery(
            select=exposure_query_select,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=exposure_conditions),
            group_by=cast(list[ast.Expr], exposure_query_group_by),
        )

    # IDENTICAL TO EXPERIMENT QUERY RUNNER
    def _get_metric_events_query(self, exposure_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Returns the query to get the relevant metric events. One row per event, so multiple rows per entity.
        Columns: timestamp, entity_identifier, variant, value
        """
        match self.metric:
            case ExperimentMeanMetric() as metric:
                match metric.source:
                    case ExperimentDataWarehouseNode():
                        return ast.SelectQuery(
                            select=[
                                ast.Alias(
                                    alias="timestamp",
                                    expr=ast.Field(chain=[metric.source.table_name, metric.source.timestamp_field]),
                                ),
                                ast.Alias(
                                    alias="entity_identifier",
                                    expr=ast.Field(
                                        chain=[
                                            metric.source.table_name,
                                            *metric.source.data_warehouse_join_key.split("."),
                                        ]
                                    ),
                                ),
                                ast.Field(chain=["exposure_data", "variant"]),
                                ast.Alias(alias="value", expr=get_metric_value(self.metric)),
                            ],
                            select_from=ast.JoinExpr(
                                table=ast.Field(chain=[metric.source.table_name]),
                                next_join=ast.JoinExpr(
                                    table=exposure_query,
                                    join_type="INNER JOIN",
                                    alias="exposure_data",
                                    constraint=ast.JoinConstraint(
                                        expr=ast.CompareOperation(
                                            left=ast.Field(
                                                chain=[
                                                    metric.source.table_name,
                                                    *metric.source.data_warehouse_join_key.split("."),
                                                ]
                                            ),
                                            right=ast.Call(
                                                name="toString",
                                                args=[ast.Field(chain=["exposure_data", "exposure_identifier"])],
                                            ),
                                            op=ast.CompareOperationOp.Eq,
                                        ),
                                        constraint_type="ON",
                                    ),
                                ),
                            ),
                            where=ast.And(
                                exprs=[
                                    *self._get_metric_time_window(
                                        left=ast.Field(chain=[metric.source.table_name, metric.source.timestamp_field])
                                    ),
                                ],
                            ),
                        )

                    case EventsNode() | ActionsNode() as metric_source:
                        return ast.SelectQuery(
                            select=[
                                ast.Field(chain=["events", "timestamp"]),
                                ast.Alias(alias="entity_id", expr=ast.Field(chain=["events", self.entity_key])),
                                ast.Field(chain=["exposure_data", "variant"]),
                                ast.Field(chain=["events", "event"]),
                                ast.Alias(alias="value", expr=get_metric_value(self.metric)),
                            ],
                            select_from=ast.JoinExpr(
                                table=ast.Field(chain=["events"]),
                                next_join=ast.JoinExpr(
                                    table=exposure_query,
                                    join_type="INNER JOIN",
                                    alias="exposure_data",
                                    constraint=ast.JoinConstraint(
                                        expr=ast.CompareOperation(
                                            left=ast.Field(chain=["events", self.entity_key]),
                                            right=ast.Field(chain=["exposure_data", "entity_id"]),
                                            op=ast.CompareOperationOp.Eq,
                                        ),
                                        constraint_type="ON",
                                    ),
                                ),
                            ),
                            where=ast.And(
                                exprs=[
                                    *self._get_metric_time_window(left=ast.Field(chain=["events", "timestamp"])),
                                    event_or_action_to_filter(self.team, metric_source),
                                    *get_test_accounts_filter(self.team, self.experiment.exposure_criteria),
                                ],
                            ),
                        )

            case ExperimentFunnelMetric() as metric:
                # Pre-calculate step conditions to avoid property resolution issues in UDF
                # For each step in the funnel, we create a new column that is 1 if the step is true, 0 otherwise
                step_selects = []
                for i, funnel_step in enumerate(metric.series):
                    step_filter = event_or_action_to_filter(self.team, funnel_step)
                    step_selects.append(
                        ast.Alias(
                            alias=f"step_{i}",
                            expr=ast.Call(name="if", args=[step_filter, ast.Constant(value=1), ast.Constant(value=0)]),
                        )
                    )

                return ast.SelectQuery(
                    select=[
                        ast.Field(chain=["events", "timestamp"]),
                        ast.Alias(alias="entity_id", expr=ast.Field(chain=["events", self.entity_key])),
                        ast.Field(chain=["exposure_data", "variant"]),
                        ast.Field(chain=["events", "event"]),
                        ast.Field(chain=["events", "uuid"]),
                        ast.Field(chain=["events", "properties"]),
                        *step_selects,
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            table=exposure_query,
                            join_type="INNER JOIN",
                            alias="exposure_data",
                            constraint=ast.JoinConstraint(
                                expr=ast.CompareOperation(
                                    left=ast.Field(chain=["events", self.entity_key]),
                                    right=ast.Field(chain=["exposure_data", "entity_id"]),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                                constraint_type="ON",
                            ),
                        ),
                    ),
                    where=ast.And(
                        exprs=[
                            *self._get_metric_time_window(left=ast.Field(chain=["events", "timestamp"])),
                            *get_test_accounts_filter(self.team, self.experiment.exposure_criteria),
                            funnel_steps_to_filter(self.team, metric.series),
                        ],
                    ),
                )

            case _:
                raise ValueError(f"Unsupported metric: {self.metric}")

    # IDENTICAL TO EXPERIMENT QUERY RUNNER
    def _get_metric_aggregation_expr(self) -> ast.Expr:
        match self.metric:
            case ExperimentMeanMetric() as metric:
                match metric.source.math:
                    case ExperimentMetricMathType.UNIQUE_SESSION:
                        return parse_expr("toFloat(count(distinct metric_events.value))")
                    case ExperimentMetricMathType.MIN:
                        return parse_expr("min(coalesce(toFloat(metric_events.value), 0))")
                    case ExperimentMetricMathType.MAX:
                        return parse_expr("max(coalesce(toFloat(metric_events.value), 0))")
                    case ExperimentMetricMathType.AVG:
                        return parse_expr("avg(coalesce(toFloat(metric_events.value), 0))")
                    case _:
                        return parse_expr("sum(coalesce(toFloat(metric_events.value), 0))")
            case ExperimentFunnelMetric():
                return funnel_evaluation_expr(self.team, self.metric, events_alias="metric_events")

    # IDENTICAL TO EXPERIMENT QUERY RUNNER
    def _get_winsorized_metric_values_query(self, metric_events_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Returns the query to winsorize metric values
        One row per entity where the value is winsorized to the lower and upper bounds
        Columns: variant, entity_id, value (winsorized metric values)
        """

        if not isinstance(self.metric, ExperimentMeanMetric):
            return metric_events_query

        if self.metric.lower_bound_percentile is not None:
            lower_bound_expr = parse_expr(
                "quantile({level})(value)",
                placeholders={"level": ast.Constant(value=self.metric.lower_bound_percentile)},
            )
        else:
            lower_bound_expr = parse_expr("min(value)")

        if self.metric.upper_bound_percentile is not None:
            upper_bound_expr = parse_expr(
                "quantile({level})(value)",
                placeholders={"level": ast.Constant(value=self.metric.upper_bound_percentile)},
            )
        else:
            upper_bound_expr = parse_expr("max(value)")

        percentiles = ast.SelectQuery(
            select=[
                ast.Alias(alias="lower_bound", expr=lower_bound_expr),
                ast.Alias(alias="upper_bound", expr=upper_bound_expr),
            ],
            select_from=ast.JoinExpr(table=metric_events_query, alias="metric_events"),
        )

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["metric_events", "variant"]),
                ast.Field(chain=["metric_events", "entity_id"]),
                ast.Alias(
                    expr=parse_expr(
                        "least(greatest(percentiles.lower_bound, metric_events.value), percentiles.upper_bound)"
                    ),
                    alias="value",
                ),
            ],
            select_from=ast.JoinExpr(
                table=metric_events_query,
                alias="metric_events",
                next_join=ast.JoinExpr(table=percentiles, alias="percentiles", join_type="CROSS JOIN"),
            ),
        )

    # SIMILAR TO _get_metrics_aggregated_per_entity_query - the only difference is that we additionally group by date
    def _get_daily_entity_metrics_query(self, exposure_query: ast.SelectQuery, metric_events_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Returns a query that gets daily metric values per entity
        Columns: variant, entity_id, date, value
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["exposures", "variant"]),
                ast.Field(chain=["exposures", "entity_id"]),
                ast.Alias(
                    alias="date",
                    expr=ast.Call(
                        name="toDate",
                        args=[ast.Field(chain=["metric_events", "timestamp"])],
                    ),
                ),
                ast.Alias(
                    expr=self._get_metric_aggregation_expr(),
                    alias="value",
                ),
            ],
            select_from=ast.JoinExpr(
                table=exposure_query,
                alias="exposures",
                next_join=ast.JoinExpr(
                    table=metric_events_query,
                    join_type="INNER JOIN",
                    alias="metric_events",
                    constraint=ast.JoinConstraint(
                        expr=ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    left=parse_expr("toString(exposures.exposure_identifier)"),
                                    right=parse_expr("toString(metric_events.entity_identifier)"),
                                    op=ast.CompareOperationOp.Eq,
                                )
                                if self.is_data_warehouse_query
                                else ast.CompareOperation(
                                    left=parse_expr("toString(exposures.entity_id)"),
                                    right=parse_expr("toString(metric_events.entity_id)"),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                            ]
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            group_by=[
                ast.Field(chain=["exposures", "variant"]),
                ast.Field(chain=["exposures", "entity_id"]),
                ast.Call(
                    name="toDate",
                    args=[ast.Field(chain=["metric_events", "timestamp"])],
                ),
            ],
        )

    # NEW SUBQUERY
    def _get_daily_aggregated_query(self, daily_entity_metrics_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Creates a daily aggregated query that groups by variant and date
        Columns: variant, date, daily_num_users, daily_total_sum, daily_total_sum_of_squares
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["daily_metrics", "variant"]),
                ast.Field(chain=["daily_metrics", "date"]),
                ast.Alias(
                    alias="daily_num_users",
                    expr=ast.Call(
                        name="countIf",
                        args=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["daily_metrics", "value"]),
                                right=ast.Constant(value=0),
                                op=ast.CompareOperationOp.Gt,
                            ),
                        ],
                    ),
                ),
                ast.Alias(
                    alias="daily_total_sum",
                    expr=ast.Call(
                        name="sum",
                        args=[ast.Field(chain=["daily_metrics", "value"])],
                    ),
                ),
                ast.Alias(
                    alias="daily_total_sum_of_squares",
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

    # NEW SUBQUERY
    def _get_cumulative_timeseries_query(self, daily_aggregated_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Creates the final timeseries query with cumulative calculations using window functions
        Columns: variant, date, num_users, total_sum, total_sum_of_squares
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["daily_agg", "variant"]),
                ast.Field(chain=["daily_agg", "date"]),
                ast.Alias(
                    alias="num_users",
                    expr=ast.WindowFunction(
                        name="sum",
                        args=[ast.Field(chain=["daily_agg", "daily_num_users"])],
                        over_expr=ast.WindowExpr(
                            partition_by=[ast.Field(chain=["daily_agg", "variant"])],
                            order_by=[ast.OrderExpr(expr=ast.Field(chain=["daily_agg", "date"]))],
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
                        args=[ast.Field(chain=["daily_agg", "daily_total_sum"])],
                        over_expr=ast.WindowExpr(
                            partition_by=[ast.Field(chain=["daily_agg", "variant"])],
                            order_by=[ast.OrderExpr(expr=ast.Field(chain=["daily_agg", "date"]))],
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
                        args=[ast.Field(chain=["daily_agg", "daily_total_sum_of_squares"])],
                        over_expr=ast.WindowExpr(
                            partition_by=[ast.Field(chain=["daily_agg", "variant"])],
                            order_by=[ast.OrderExpr(expr=ast.Field(chain=["daily_agg", "date"]))],
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
            select_from=ast.JoinExpr(table=daily_aggregated_query, alias="daily_agg"),
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["daily_agg", "variant"])),
                ast.OrderExpr(expr=ast.Field(chain=["daily_agg", "date"])),
            ],
        )

    def _get_experiment_timeseries_query(self) -> ast.SelectQuery:
        """
        Creates a timeseries query that returns cumulative daily results for each variant
        Returns one row per (variant, date) combination with cumulative statistics
        Columns: variant, date, num_users, total_sum, total_sum_of_squares
        """
        # Get all entities that should be included in the experiment
        exposure_query = self._get_exposure_query()

        # Get all metric events that are relevant to the experiment
        metric_events_query = self._get_metric_events_query(exposure_query)

        # Get daily metric values per entity
        daily_entity_metrics_query = self._get_daily_entity_metrics_query(exposure_query, metric_events_query)

        # Winsorize if needed
        if isinstance(self.metric, ExperimentMeanMetric) and (
            self.metric.lower_bound_percentile or self.metric.upper_bound_percentile
        ):
            daily_entity_metrics_query = self._get_winsorized_metric_values_query(daily_entity_metrics_query)

        # Daily aggregated query that groups by variant and date
        daily_aggregated_query = self._get_daily_aggregated_query(daily_entity_metrics_query)

        # Final timeseries query with cumulative calculations using window functions
        return self._get_cumulative_timeseries_query(daily_aggregated_query)

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

        grouped_by_date = {}
        for variant, date, num_users, total_sum, total_sum_of_squares in results:
            date_str = f"{date.isoformat()}T00:00:00Z"
            if date_str not in grouped_by_date:
                grouped_by_date[date_str] = []
            
            grouped_by_date[date_str].append({
                "key": variant,
                "number_of_samples": num_users,
                "sum": total_sum,
                "sum_squares": total_sum_of_squares,
            })

        return [
            {
                "date": date_str,
                "variant_results": variant_data
            }
            for date_str, variant_data in sorted(grouped_by_date.items())
        ]
    
    def _create_experiment_stats_base(self, variant: str, num_users: int, total_sum: float, total_sum_of_squares: float) -> ExperimentStatsBase:
        """Create an ExperimentStatsBase object for a variant's daily results"""
        return ExperimentStatsBase(
            key=variant,
            number_of_samples=num_users,
            sum=total_sum,
            sum_squares=total_sum_of_squares,
        )

    def handle(self, *args, **options):
        experiment_id = options.get("experiment_id")
        
        try:
            self.experiment = Experiment.objects.get(id=experiment_id)
            self.feature_flag = self.experiment.feature_flag
            self.team = self.experiment.team

            self.group_type_index = self.feature_flag.filters.get("aggregation_group_type_index")
            self.entity_key = get_entity_key(self.group_type_index)
            self.variants = [variant["key"] for variant in self.feature_flag.variants]
            if self.experiment.holdout:
                self.variants.append(f"holdout-{self.experiment.holdout.id}")
            
            self.date_range = self._get_date_range()
            self.date_range_query = QueryDateRange(
                date_range=self.date_range,
                team=self.team,
                interval=IntervalType.DAY,
                now=datetime.now(),
            )
            
            self.multiple_variant_handling = get_multiple_variant_handling_from_experiment(self.experiment)
            
            # Get the first metric and parse it
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
                print("No metrics found for this experiment")
                return

            self.is_data_warehouse_query = (
                isinstance(self.metric, ExperimentMeanMetric)
                and isinstance(self.metric.source, ExperimentDataWarehouseNode)
            )

            experiment_query = self._get_experiment_timeseries_query()

            self.timings = HogQLTimings()
            response = execute_hogql_query(
                query_type="ExperimentQuery",
                query=experiment_query,
                team=self.team,
                timings=self.timings,
                modifiers=create_default_modifiers_for_team(self.team),
                settings=HogQLGlobalSettings(max_execution_time=180),
            )

            print(f"Columns: {response.columns}")
            print(f"Query results: {response.results}")
            print(f"Total rows: {len(response.results)}")

            transformed_results = self._transform_timeseries_results(response.results)
            print(f"\nTransformed results: {transformed_results}")

        except Exception as e:
            logger.error(f"Error fetching experiment: {e}")
            print(f"Error fetching experiment: {e}")
