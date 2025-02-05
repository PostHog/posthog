from zoneinfo import ZoneInfo
from posthog.hogql import ast
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.experiments import CONTROL_VARIANT_KEY
from posthog.hogql_queries.experiments.types import ExperimentMetricType
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
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models.experiment import Experiment
from posthog.queries.trends.util import ALL_SUPPORTED_MATH_FUNCTIONS
from rest_framework.exceptions import ValidationError
from posthog.schema import (
    CachedExperimentTrendsQueryResponse,
    ExperimentSignificanceCode,
    ExperimentTrendsQuery,
    ExperimentTrendsQueryResponse,
    ExperimentVariantTrendsBaseStats,
    DateRange,
    PropertyMathType,
    TrendsQuery,
)
from typing import Optional
from datetime import datetime, timedelta, UTC


class ExperimentQueryRunner(QueryRunner):
    query: ExperimentTrendsQuery
    response: ExperimentTrendsQueryResponse
    cached_response: CachedExperimentTrendsQueryResponse
    response: ExperimentTrendsQueryResponse
    cached_response: CachedExperimentTrendsQueryResponse

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
        self._fix_math_aggregation()

    def _get_metric_type(self) -> ExperimentMetricType:
        # Currently, we rely on the math type to determine the metric type
        match self.query.count_query.series[0].math:
            case PropertyMathType.SUM | "hogql":
                return ExperimentMetricType.CONTINUOUS
            case _:
                return ExperimentMetricType.COUNT

    def _uses_math_aggregation_by_user_or_property_value(self, query: TrendsQuery):
        math_keys = ALL_SUPPORTED_MATH_FUNCTIONS
        # "sum" doesn't need special handling, we *can* have custom exposure for sum filters
        if "sum" in math_keys:
            math_keys.remove("sum")
        return any(entity.math in math_keys for entity in query.series)

    def _fix_math_aggregation(self):
        """
        Switch unsupported math aggregations to SUM
        """
        uses_math_aggregation = self._uses_math_aggregation_by_user_or_property_value(self.query.count_query)
        if uses_math_aggregation:
            self.query.count_query.series[0].math = PropertyMathType.SUM

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

        # Get the metric event we should filter on
        metric_event = self.query.count_query.series[0].event

        # Pick the correct value for the aggregation chosen
        match self._get_metric_type():
            case ExperimentMetricType.CONTINUOUS:
                # If the metric type is continuous, we need to extract the value from the event property
                metric_property = self.query.count_query.series[0].math_property
                metric_value = f"toFloat(JSONExtractRaw(properties, '{metric_property}'))"
            case _:
                # Else, we default to count
                # We then just emit 1 so we can easily sum it up
                metric_value = "1"

        # Filter Test Accounts
        test_accounts_filter: list[ast.Expr] = []
        if (
            self.query.count_query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for property in self.team.test_account_filters:
                test_accounts_filter.append(property_to_expr(property, self.team))

        # Exposures, find those to include in the experiment
        # One row per entity, with the variant and first exposure time
        # Currently grouping by distinct_id, but this would be changed to group_id or session_id,
        # if that is the chosen aggregation
        exposure_query = ast.SelectQuery(
            select=[
                ast.Field(chain=["distinct_id"]),
                parse_expr("replaceAll(JSONExtractRaw(properties, '$feature_flag_response'), '\"', '') AS variant"),
                parse_expr("min(timestamp) as first_exposure_time"),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    parse_expr(
                        f"event = '$feature_flag_called' and replaceAll(JSONExtractRaw(properties, '$feature_flag'), '\"', '') = '{feature_flag_key}' "
                    ),
                    *test_accounts_filter,
                ]
            ),
            group_by=[ast.Field(chain=["variant"]), ast.Field(chain=["distinct_id"])],
        )

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
                    parse_expr(f"event = '{metric_event}'"),
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

    def _evaluate_experiment_query(self) -> list[ExperimentVariantTrendsBaseStats]:
        response = execute_hogql_query(
            query=self._get_experiment_query(),
            team=self.team,
            timings=self.timings,
            modifiers=create_default_modifiers_for_team(self.team),
        )

        variants: list[ExperimentVariantTrendsBaseStats] = [
            ExperimentVariantTrendsBaseStats(
                absolute_exposure=result[1],
                count=result[2],
                exposure=result[1],
                key=result[0],
            )
            for result in response.results
        ]

        return variants

    def calculate(self) -> ExperimentTrendsQueryResponse:
        variants = self._evaluate_experiment_query()

        control_variant = next((variant for variant in variants if variant.key == CONTROL_VARIANT_KEY), None)
        test_variants = [variant for variant in variants if variant.key != CONTROL_VARIANT_KEY]

        if not control_variant:
            raise ValueError("Control variant not found in experiment results")

        # Statistical analysis
        if self.stats_version == 2:
            match self._get_metric_type():
                case ExperimentMetricType.CONTINUOUS:
                    probabilities = calculate_probabilities_v2_continuous(control_variant, test_variants)
                    significance_code, p_value = are_results_significant_v2_continuous(
                        control_variant, test_variants, probabilities
                    )
                    credible_intervals = calculate_credible_intervals_v2_continuous([control_variant, *test_variants])
                case ExperimentMetricType.COUNT:
                    probabilities = calculate_probabilities_v2_count(control_variant, test_variants)
                    significance_code, p_value = are_results_significant_v2_count(
                        control_variant, test_variants, probabilities
                    )
                    credible_intervals = calculate_credible_intervals_v2_count([control_variant, *test_variants])
                case _:
                    raise ValueError(f"Unsupported metric type: {self._get_metric_type()}")
        else:
            probabilities = calculate_probabilities(control_variant, test_variants)
            significance_code, p_value = are_results_significant(control_variant, test_variants, probabilities)
            credible_intervals = calculate_credible_intervals([control_variant, *test_variants])

        return ExperimentTrendsQueryResponse(
            kind="ExperimentTrendsQuery",
            insight=[],
            count_query=None,
            exposure_query=None,
            variants=[variant.model_dump() for variant in [control_variant, *test_variants]],
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
        raise ValueError(f"Cannot convert source query of type {self.query.count_query.kind} to query")

    # Cache results for 24 hours
    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        return last_refresh + timedelta(hours=24)

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        if not last_refresh:
            return True
        return (datetime.now(UTC) - last_refresh) > timedelta(hours=24)
