from zoneinfo import ZoneInfo
from posthog.hogql import ast
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.experiments import CONTROL_VARIANT_KEY
from posthog.hogql_queries.experiments.trends_statistics import (
    are_results_significant,
    calculate_credible_intervals,
    calculate_probabilities,
)
from posthog.hogql_queries.experiments.trends_statistics_v2_count import (
    are_results_significant_v2_count,
    calculate_credible_intervals_v2_count,
    calculate_probabilities_v2_count,
)
from posthog.hogql_queries.experiments.trends_statistics_v2_continuous import (
    are_results_significant_v2_continuous,
    calculate_credible_intervals_v2_continuous,
    calculate_probabilities_v2_continuous,
)
from posthog.hogql_queries.experiments.funnels_statistics_v2 import (
    calculate_probabilities_v2 as calculate_probabilities_v2_funnel,
    are_results_significant_v2 as are_results_significant_v2_funnel,
    calculate_credible_intervals_v2 as calculate_credible_intervals_v2_funnel,
)
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.experiment import Experiment
from rest_framework.exceptions import ValidationError
from posthog.schema import (
    CachedExperimentQueryResponse,
    ExperimentDataWarehouseMetricConfig,
    ExperimentEventMetricConfig,
    ExperimentMetricType,
    ExperimentQueryResponse,
    ExperimentSignificanceCode,
    ExperimentQuery,
    ExperimentVariantFunnelsBaseStats,
    ExperimentVariantTrendsBaseStats,
    DateRange,
    IntervalType,
)
from typing import Optional, cast
from datetime import datetime, timedelta, UTC


class ExperimentQueryRunner(QueryRunner):
    query: ExperimentQuery
    response: ExperimentQueryResponse
    cached_response: CachedExperimentQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.query.experiment_id:
            raise ValidationError("experiment_id is required")

        self.experiment = Experiment.objects.get(id=self.query.experiment_id)
        self.feature_flag = self.experiment.feature_flag
        self.variants = [variant["key"] for variant in self.feature_flag.variants]
        if self.experiment.holdout:
            self.variants.append(f"holdout-{self.experiment.holdout.id}")

        self.stats_version = self.experiment.get_stats_config("version") or 1

        self.date_range = self._get_date_range()

        # Just to simplify access
        self.metric = self.query.metric

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

    def _get_experiment_query(self) -> ast.SelectQuery:
        # Lots of shortcuts taken here, but it's a proof of concept to illustrate the idea

        feature_flag_key = self.feature_flag.key

        is_data_warehouse_query = isinstance(self.metric.metric_config, ExperimentDataWarehouseMetricConfig)

        # Experiment identifiers
        experiment_identifiers = [
            ast.Field(chain=["distinct_id"]),
            # here we will also add group_id, etc.
        ]

        if is_data_warehouse_query:
            metric_config = self.metric.metric_config
            experiment_identifiers += [
                parse_expr(metric_config.events_id_field),
            ]

        # Pick the correct value for the aggregation chosen
        match self.metric.metric_type:
            case ExperimentMetricType.CONTINUOUS:
                # If the metric type is continuous, we need to extract the value from the event property
                metric_property = self.metric.metric_config.math_property
                if is_data_warehouse_query:
                    metric_value = f"toFloat('{metric_property}')"
                else:
                    metric_value = f"toFloat(JSONExtractRaw(properties, '{metric_property}'))"
            case _:
                # Else, we default to count
                # We then just emit 1 so we can easily sum it up
                metric_value = "1"

        # Filter Test Accounts
        test_accounts_filter: list[ast.Expr] = []
        if (
            self.metric.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for property in self.team.test_account_filters:
                test_accounts_filter.append(property_to_expr(property, self.team))

        # Property filters
        metric_property_filters: list[ast.Expr] = []
        if isinstance(self.metric.metric_config, ExperimentEventMetricConfig) and self.metric.metric_config.properties:
            for property in self.metric.metric_config.properties:
                metric_property_filters.append(property_to_expr(property, self.team))

        date_range_query = QueryDateRange(
            date_range=self.date_range,
            team=self.team,
            interval=IntervalType.DAY,
            now=datetime.now(),
        )

        # Exposures, find those to include in the experiment
        # One row per entity, with the variant and first exposure time
        # Currently grouping by distinct_id, but this would be changed to group_id or session_id,
        # if that is the chosen aggregation
        exposure_query = ast.SelectQuery(
            select=[
                *experiment_identifiers,
                parse_expr("replaceAll(JSONExtractRaw(properties, '$feature_flag_response'), '\"', '') AS variant"),
                parse_expr("min(timestamp) as first_exposure_time"),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    parse_expr(
                        f"event = '$feature_flag_called' and replaceAll(JSONExtractRaw(properties, '$feature_flag'), '\"', '') = '{feature_flag_key}' "
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=date_range_query.date_from()),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.LtEq,
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=date_range_query.date_to()),
                    ),
                    *test_accounts_filter,
                ]
            ),
            group_by=[ast.Field(chain=["variant"]), *experiment_identifiers],
        )

        match self.metric.metric_config:
            case ExperimentDataWarehouseMetricConfig() as metric_config:
                events_after_exposure_query = ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="timestamp",
                            expr=ast.Field(chain=[metric_config.table_name, metric_config.table_timestamp_field]),
                        ),
                        ast.Alias(
                            alias="distinct_id",
                            expr=ast.Field(chain=["exposure", "distinct_id"]),
                        ),
                        ast.Field(chain=["exposure", "variant"]),
                        parse_expr(f"{metric_value} as value"),
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=[metric_config.table_name]),
                        next_join=ast.JoinExpr(
                            table=exposure_query,
                            join_type="INNER JOIN",
                            alias="exposure",
                            constraint=ast.JoinConstraint(
                                expr=ast.CompareOperation(
                                    left=ast.Field(chain=[metric_config.table_name, metric_config.table_id_field]),
                                    # TODO: Figure out how to "extract" ex. customer_id from the chained field, ex. customer.customer_id
                                    right=ast.Field(chain=["exposure", "customer_id"]),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                                constraint_type="ON",
                            ),
                        ),
                    ),
                    where=ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=ast.Field(chain=[metric_config.table_name, metric_config.table_timestamp_field]),
                                right=ast.Field(chain=["exposure", "first_exposure_time"]),
                                op=ast.CompareOperationOp.GtEq,
                            ),
                            # :TODO: Figure out if we actually need this
                            # parse_expr(f"event = '{self.query.count_query.series[0].event}'"),
                        ],
                    ),
                )

            case ExperimentEventMetricConfig() as metric_config:
                # Metric events seen after exposure
                # One row per event
                events_after_exposure_query = ast.SelectQuery(
                    select=[
                        ast.Field(chain=["events", "timestamp"]),
                        ast.Field(chain=["events", "distinct_id"]),
                        ast.Field(chain=["exposure", "variant"]),
                        ast.Field(chain=["events", "event"]),
                        parse_expr(f"{metric_value} as value"),
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            table=exposure_query,
                            join_type="INNER JOIN",
                            alias="exposure",
                            constraint=ast.JoinConstraint(
                                expr=ast.CompareOperation(
                                    left=ast.Field(chain=["events", "distinct_id"]),
                                    right=ast.Field(chain=["exposure", "distinct_id"]),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                                constraint_type="ON",
                            ),
                        ),
                    ),
                    where=ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["events", "timestamp"]),
                                right=ast.Field(chain=["exposure", "first_exposure_time"]),
                                op=ast.CompareOperationOp.GtEq,
                            ),
                            parse_expr(f"event = '{metric_config.event}'"),
                            *metric_property_filters,
                        ],
                    ),
                )

        metrics_aggregated_per_entity_query = ast.SelectQuery(
            select=[
                ast.Field(chain=["base", "variant"]),
                ast.Field(chain=["base", "distinct_id"]),
                parse_expr("sum(coalesce(eae.value, 0)) as value"),
            ],
            select_from=ast.JoinExpr(
                table=exposure_query,
                alias="base",
                next_join=ast.JoinExpr(
                    table=events_after_exposure_query,
                    join_type="LEFT JOIN",
                    alias="eae",
                    constraint=ast.JoinConstraint(
                        expr=ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    left=ast.Field(chain=["base", "distinct_id"]),
                                    right=ast.Field(chain=["eae", "distinct_id"]),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                                ast.CompareOperation(
                                    left=ast.Field(chain=["base", "variant"]),
                                    right=ast.Field(chain=["eae", "variant"]),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                            ]
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            group_by=[
                ast.Field(chain=["base", "variant"]),
                ast.Field(chain=["base", "distinct_id"]),
            ],
        )

        # Here we coumpute what we need for our statistical analysis
        # We are aggregating population metrics per variant, so we can easily compute the mean and variance
        # This is part of our methodology and not depending on the chosen metric
        experiment_variant_results_query = ast.SelectQuery(
            select=[
                ast.Field(chain=["maq", "variant"]),
                parse_expr("count(maq.distinct_id) as num_users"),
                parse_expr("sum(maq.value) as total_sum"),
                parse_expr("sum(power(maq.value, 2)) as total_sum_of_squares"),
            ],
            select_from=ast.JoinExpr(table=metrics_aggregated_per_entity_query, alias="maq"),
            group_by=[ast.Field(chain=["maq", "variant"])],
        )

        return experiment_variant_results_query

    def _evaluate_experiment_query(
        self,
    ) -> list[ExperimentVariantTrendsBaseStats] | list[ExperimentVariantFunnelsBaseStats]:
        response = execute_hogql_query(
            query=self._get_experiment_query(),
            team=self.team,
            timings=self.timings,
            modifiers=create_default_modifiers_for_team(self.team),
        )

        if self.metric.metric_type == ExperimentMetricType.FUNNEL:
            return [
                ExperimentVariantFunnelsBaseStats(
                    failure_count=result[1] - result[2],
                    key=result[0],
                    success_count=result[2],
                )
                for result in response.results
            ]

        return [
            ExperimentVariantTrendsBaseStats(
                absolute_exposure=result[1],
                count=result[2],
                exposure=result[1],
                key=result[0],
            )
            for result in response.results
        ]

    def calculate(self) -> ExperimentQueryResponse:
        variants = self._evaluate_experiment_query()

        control_variant = next((variant for variant in variants if variant.key == CONTROL_VARIANT_KEY), None)
        test_variants = [variant for variant in variants if variant.key != CONTROL_VARIANT_KEY]

        if not control_variant:
            raise ValueError("Control variant not found in experiment results")

        # Statistical analysis
        if self.stats_version == 2:
            match self.metric.metric_type:
                case ExperimentMetricType.CONTINUOUS:
                    probabilities = calculate_probabilities_v2_continuous(
                        control_variant=cast(ExperimentVariantTrendsBaseStats, control_variant),
                        test_variants=cast(list[ExperimentVariantTrendsBaseStats], test_variants),
                    )
                    significance_code, p_value = are_results_significant_v2_continuous(
                        control_variant=cast(ExperimentVariantTrendsBaseStats, control_variant),
                        test_variants=cast(list[ExperimentVariantTrendsBaseStats], test_variants),
                        probabilities=probabilities,
                    )
                    credible_intervals = calculate_credible_intervals_v2_continuous([control_variant, *test_variants])
                case ExperimentMetricType.COUNT:
                    probabilities = calculate_probabilities_v2_count(
                        cast(ExperimentVariantTrendsBaseStats, control_variant),
                        cast(list[ExperimentVariantTrendsBaseStats], test_variants),
                    )
                    significance_code, p_value = are_results_significant_v2_count(
                        cast(ExperimentVariantTrendsBaseStats, control_variant),
                        cast(list[ExperimentVariantTrendsBaseStats], test_variants),
                        probabilities,
                    )
                    credible_intervals = calculate_credible_intervals_v2_count([control_variant, *test_variants])
                case ExperimentMetricType.FUNNEL:
                    probabilities = calculate_probabilities_v2_funnel(
                        cast(ExperimentVariantFunnelsBaseStats, control_variant),
                        cast(list[ExperimentVariantFunnelsBaseStats], test_variants),
                    )
                    significance_code, p_value = are_results_significant_v2_funnel(
                        cast(ExperimentVariantFunnelsBaseStats, control_variant),
                        cast(list[ExperimentVariantFunnelsBaseStats], test_variants),
                        probabilities,
                    )
                    credible_intervals = calculate_credible_intervals_v2_funnel(
                        cast(list[ExperimentVariantFunnelsBaseStats], [control_variant, *test_variants])
                    )
                case _:
                    raise ValueError(f"Unsupported metric type: {self.metric.metric_type}")
        else:
            probabilities = calculate_probabilities(
                cast(ExperimentVariantTrendsBaseStats, control_variant),
                cast(list[ExperimentVariantTrendsBaseStats], test_variants),
            )
            significance_code, p_value = are_results_significant(
                cast(ExperimentVariantTrendsBaseStats, control_variant),
                cast(list[ExperimentVariantTrendsBaseStats], test_variants),
                probabilities,
            )
            credible_intervals = calculate_credible_intervals([control_variant, *test_variants])

        return ExperimentQueryResponse(
            kind="ExperimentQuery",
            insight=[],
            metric=self.metric,
            variants=variants,
            probability={
                variant.key: probability
                for variant, probability in zip([control_variant, *test_variants], probabilities)
            },
            significant=significance_code == ExperimentSignificanceCode.SIGNIFICANT,
            significance_code=significance_code,
            stats_version=self.stats_version,
            p_value=p_value,
            credible_intervals=credible_intervals,
        )

    def to_query(self) -> ast.SelectQuery:
        raise ValueError(f"Cannot convert source query of type {self.query.metric.kind} to query")

    # Cache results for 24 hours
    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        return last_refresh + timedelta(hours=24)

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        if not last_refresh:
            return True
        return (datetime.now(UTC) - last_refresh) > timedelta(hours=24)
