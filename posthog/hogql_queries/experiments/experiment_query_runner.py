from datetime import UTC, datetime, timedelta
from typing import Optional

import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    CachedExperimentQueryResponse,
    ExperimentActorsQuery,
    ExperimentBreakdownResult,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentStatsBase,
    IntervalType,
    MultipleVariantHandling,
    PrecomputationMode,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.hogql_queries.experiments import CONTROL_VARIANT_KEY, MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.experiments.base_query_utils import get_experiment_date_range
from posthog.hogql_queries.experiments.error_handling import experiment_error_handler
from posthog.hogql_queries.experiments.experiment_query_builder import (
    ExperimentQueryBuilder,
    get_exposure_config_params_for_builder,
)
from posthog.hogql_queries.experiments.exposure_query_logic import (
    get_entity_key,
    get_multiple_variant_handling_from_experiment,
)
from posthog.hogql_queries.experiments.utils import (
    aggregate_variants_across_breakdowns,
    get_bayesian_experiment_result,
    get_experiment_query_debug,
    get_experiment_stats_method,
    get_frequentist_experiment_result,
    get_variant_results,
    split_baseline_and_test_variants,
)
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.extensions import get_or_create_team_extension

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
)
from products.experiments.backend.metric_utils import get_default_metric_title
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

logger = structlog.get_logger(__name__)

# Variable TTL for experiment exposure lazy computation
# Current day refreshes frequently (data arriving), old data cached long
DEFAULT_EXPOSURE_TTL_SECONDS = {
    "0d": 15 * 60,  # 15 min
    "1d": 60 * 60,  # 1 hour
    "default": 60 * 24 * 60 * 60,  # 60 days - data frozen
}

MAX_EXECUTION_TIME = 600
MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY = 37 * 1024 * 1024 * 1024  # 37 GB


class ExperimentQueryRunner(QueryRunner):
    query: ExperimentQuery
    cached_response: CachedExperimentQueryResponse
    actors_query: Optional[ExperimentActorsQuery] = None

    def __init__(
        self,
        *args,
        override_end_date: Optional[datetime] = None,
        user_facing: bool = True,
        max_execution_time: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.override_end_date = override_end_date
        self.user_facing = user_facing
        self.max_execution_time = max_execution_time if max_execution_time is not None else MAX_EXECUTION_TIME

        if not self.query.experiment_id:
            raise ValidationError("experiment_id is required")

        try:
            self.experiment = Experiment.objects.get(id=self.query.experiment_id, team=self.team)
        except Experiment.DoesNotExist:
            raise ValidationError(f"Experiment with id {self.query.experiment_id} not found")
        self.feature_flag = self.experiment.feature_flag
        self.group_type_index = self.feature_flag.filters.get("aggregation_group_type_index")
        self.entity_key = get_entity_key(self.group_type_index)

        self.variants = [variant["key"] for variant in self.feature_flag.variants]
        if self.experiment.holdout:
            self.variants.append(f"holdout-{self.experiment.holdout.id}")

        stats_config = self.experiment.stats_config or {}
        self.baseline_variant_key = stats_config.get("baseline_variant_key", CONTROL_VARIANT_KEY)

        self.date_range = get_experiment_date_range(self.experiment, self.team, self.override_end_date)
        self.date_range_query = QueryDateRange(
            date_range=self.date_range,
            team=self.team,
            interval=IntervalType.DAY,
            now=datetime.now(),
        )
        # Check if this is a data warehouse query
        if isinstance(self.query.metric, ExperimentMeanMetric):
            self.is_data_warehouse_query = self.query.metric.source.kind == "ExperimentDataWarehouseNode"
        elif isinstance(self.query.metric, ExperimentRatioMetric):
            # For ratio metrics, check if either numerator or denominator uses data warehouse
            numerator_is_dw = isinstance(self.query.metric.numerator, ExperimentDataWarehouseNode)
            denominator_is_dw = isinstance(self.query.metric.denominator, ExperimentDataWarehouseNode)
            self.is_data_warehouse_query = numerator_is_dw or denominator_is_dw
        elif isinstance(self.query.metric, ExperimentRetentionMetric):
            # For retention metrics, check if either start_event or completion_event uses data warehouse
            start_is_dw = isinstance(self.query.metric.start_event, ExperimentDataWarehouseNode)
            completion_is_dw = isinstance(self.query.metric.completion_event, ExperimentDataWarehouseNode)
            self.is_data_warehouse_query = start_is_dw or completion_is_dw
        else:
            self.is_data_warehouse_query = False
        self.is_ratio_metric = isinstance(self.query.metric, ExperimentRatioMetric)

        self.stats_method = get_experiment_stats_method(self.experiment)

        self.multiple_variant_handling = get_multiple_variant_handling_from_experiment(
            self.experiment.exposure_criteria
        )

        # Just to simplify access
        self.metric = self.query.metric

        self.clickhouse_sql: str | None = None
        self.hogql: str | None = None
        self._is_precomputed: bool = False

    def _get_breakdowns_for_builder(self) -> list | None:
        """Extract and validate breakdowns from metric configuration."""
        breakdown_filter = getattr(self.metric, "breakdownFilter", None)
        if not breakdown_filter:
            return None

        breakdowns = getattr(breakdown_filter, "breakdowns", None)
        if not breakdowns or len(breakdowns) == 0:
            return None

        if len(breakdowns) > 3:
            raise ValidationError("Maximum of 3 breakdowns are supported for experiment metrics")

        return breakdowns

    def _ensure_exposures_precomputed(self, builder: ExperimentQueryBuilder) -> LazyComputationResult:
        """
        Ensures lazy-computed exposure data exists for this experiment.

        Gets the exposure query from the builder and passes it to the lazy computation
        system, which will compute and store the exposure data if not already cached.

        Returns:
            LazyComputationResult with job_ids that can be used to query the data
        """
        query_string, placeholders = builder.get_exposure_query_for_precomputation()

        if not self.experiment.start_date:
            raise ValidationError("Experiment must have a start date for lazy computation")

        date_from = self.experiment.start_date
        date_to = self.override_end_date or self.experiment.end_date or datetime.now(UTC)

        return ensure_precomputed(
            team=self.team,
            insert_query=query_string,
            time_range_start=date_from,
            time_range_end=date_to,
            ttl_seconds=DEFAULT_EXPOSURE_TTL_SECONDS,
            table=LazyComputationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
            placeholders=placeholders,
            sentinel_placeholders={"experiment_date_to"},
        )

    def _ensure_metric_events_precomputed(self, builder: ExperimentQueryBuilder) -> LazyComputationResult:
        """
        Ensures lazy-computed funnel metric event data exists for this experiment.

        Stores one row per matching event with step indicators in the
        experiment_metric_events_preaggregated table.
        """
        query_string, placeholders = builder.get_funnel_metric_events_query_for_precomputation()

        if not self.experiment.start_date:
            raise ValidationError("Experiment must have a start date for lazy computation")

        date_from = self.experiment.start_date
        date_to = self.override_end_date or self.experiment.end_date or datetime.now(UTC)

        # Extend time range by conversion window — funnel step events can occur after experiment end
        conversion_window_seconds = builder._get_conversion_window_seconds()
        if conversion_window_seconds > 0:
            date_to = date_to + timedelta(seconds=conversion_window_seconds)

        return ensure_precomputed(
            team=self.team,
            insert_query=query_string,
            time_range_start=date_from,
            time_range_end=date_to,
            ttl_seconds=DEFAULT_EXPOSURE_TTL_SECONDS,
            table=LazyComputationTable.EXPERIMENT_METRIC_EVENTS_PREAGGREGATED,
            placeholders=placeholders,
        )

    def _should_precompute(self) -> bool:
        """Resolve whether to use precomputation: query-level override > team-level default."""
        if self.query.precomputation_mode == PrecomputationMode.PRECOMPUTED:
            return True
        if self.query.precomputation_mode == PrecomputationMode.DIRECT:
            return False

        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        return config.experiment_precomputation_enabled

    def _get_experiment_query(self) -> ast.SelectQuery:
        """
        Returns the main experiment query.
        """
        assert isinstance(
            self.metric,
            ExperimentFunnelMetric | ExperimentMeanMetric | ExperimentRatioMetric | ExperimentRetentionMetric,
        )

        # Get the "missing" (not directly accessible) parameters required for the builder
        (
            exposure_config,
            multiple_variant_handling,
            filter_test_accounts,
        ) = get_exposure_config_params_for_builder(self.experiment.exposure_criteria)

        funnel_steps_data_disabled = (self.experiment.parameters or {}).get("funnel_steps_data_disabled", False)

        builder = ExperimentQueryBuilder(
            team=self.team,
            feature_flag_key=self.feature_flag.key,
            exposure_config=exposure_config,
            filter_test_accounts=filter_test_accounts,
            multiple_variant_handling=multiple_variant_handling,
            variants=self.variants,
            date_range_query=self.date_range_query,
            entity_key=self.entity_key,
            metric=self.metric,
            breakdowns=self._get_breakdowns_for_builder(),
            only_count_matured_users=self.experiment.only_count_matured_users,
            funnel_steps_data_disabled=funnel_steps_data_disabled,
        )

        should_precompute = self._should_precompute()

        # Skip precomputation for data warehouse metrics because the precomputed table
        # doesn't include the join keys needed to link exposures to data warehouse tables
        if should_precompute and not self.is_data_warehouse_query:
            try:
                result = self._ensure_exposures_precomputed(builder)
                if result.ready:
                    builder.preaggregation_job_ids = [str(job_id) for job_id in result.job_ids]
                    self._is_precomputed = True
                else:
                    logger.warning("exposure_lazy_computation_not_ready", experiment_id=self.experiment.id)
            except Exception:
                logger.exception("exposure_lazy_computation_failed", experiment_id=self.experiment.id)

            # Precompute metric events for ordered funnel metrics
            if (
                isinstance(self.metric, ExperimentFunnelMetric)
                and (self.metric.funnel_order_type or "ordered") == "ordered"
                and not self._get_breakdowns_for_builder()
                and self.query.metric_events_precomputation
            ):
                try:
                    metric_result = self._ensure_metric_events_precomputed(builder)
                    if metric_result.ready:
                        builder.metric_events_preaggregation_job_ids = [str(job_id) for job_id in metric_result.job_ids]
                    else:
                        logger.warning("metric_events_lazy_computation_not_ready", experiment_id=self.experiment.id)
                except Exception:
                    logger.exception("metric_events_lazy_computation_failed", experiment_id=self.experiment.id)

        return builder.build_query()

    def _evaluate_experiment_query(
        self,
    ) -> list[tuple]:
        # Adding experiment specific tags to the tag collection
        # This will be available as labels in Prometheus
        metric_name = self.metric.name or get_default_metric_title(self.metric.model_dump())
        tag_queries(
            product=Product.EXPERIMENTS,
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            experiment_feature_flag_key=self.feature_flag.key,
            experiment_is_data_warehouse_query=self.is_data_warehouse_query,
            experiment_metric_uuid=self.metric.uuid,
            experiment_metric_name=metric_name,
        )

        experiment_query_ast = self._get_experiment_query()

        # Tag after _get_experiment_query() which sets _is_precomputed
        tag_queries(
            experiment_execution_path="precomputed" if self._is_precomputed else "direct_scan",
        )
        experiment_query_debug = get_experiment_query_debug(experiment_query_ast, self.team)
        self.hogql = experiment_query_debug[0]
        self.clickhouse_sql = experiment_query_debug[1]

        response = execute_hogql_query(
            query_type="ExperimentQuery",
            query=experiment_query_ast,
            team=self.team,
            timings=self.timings,
            modifiers=create_default_modifiers_for_team(self.team),
            settings=HogQLGlobalSettings(
                max_execution_time=self.max_execution_time,
                enable_analyzer=True,
                max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY,
            ),
            workload=self.workload,
        )

        # Remove the $multiple variant only when using exclude handling
        if self.multiple_variant_handling == MultipleVariantHandling.EXCLUDE:
            response.results = [result for result in response.results if result[0] != MULTIPLE_VARIANT_KEY]

        sorted_results = sorted(response.results, key=lambda x: self.variants.index(x[0]))

        return sorted_results

    @experiment_error_handler
    def _calculate(self) -> ExperimentQueryResponse:
        # Prepare variant data
        variant_results = self._prepare_variant_results()

        # Process breakdowns or extract variants
        if self._has_breakdown(variant_results):
            breakdown_results, variants = self._process_breakdown_results(variant_results)
        else:
            breakdown_results = None
            variants = [v for _, v in variant_results]

        # Calculate final statistics
        result = self._calculate_statistics_for_variants(variants)

        # Attach breakdown data if present
        if breakdown_results is not None:
            result.breakdown_results = breakdown_results

        result.clickhouse_sql = self.clickhouse_sql
        result.hogql = self.hogql
        result.is_precomputed = self._is_precomputed

        return result

    def _prepare_variant_results(self) -> list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]:
        """Fetch and prepare variant results with missing variants added."""
        sorted_results = self._evaluate_experiment_query()
        variant_results = get_variant_results(sorted_results, self.metric)
        return self._add_missing_variants(variant_results)

    def _has_breakdown(self, variant_results: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]) -> bool:
        """Check if results contain breakdown data."""
        return any(bv is not None for bv, _ in variant_results)

    def _calculate_statistics_for_variants(self, variants: list[ExperimentStatsBase]) -> ExperimentQueryResponse:
        """Calculate statistical analysis results for a set of variants."""
        control_variant, test_variants = split_baseline_and_test_variants(variants, self.baseline_variant_key)

        if self.stats_method == "frequentist":
            return get_frequentist_experiment_result(
                metric=self.metric,
                control_variant=control_variant,
                test_variants=test_variants,
                stats_config=self.experiment.stats_config,
            )

        return get_bayesian_experiment_result(
            metric=self.metric,
            control_variant=control_variant,
            test_variants=test_variants,
            stats_config=self.experiment.stats_config,
        )

    def _process_breakdown_results(
        self, variant_results: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]
    ) -> tuple[list[ExperimentBreakdownResult], list[ExperimentStatsBase]]:
        """Compute per-breakdown statistics and aggregate across breakdowns."""
        breakdown_tuples = sorted({bv for bv, _ in variant_results if bv is not None})

        breakdown_results = [
            self._compute_breakdown_statistics(breakdown_tuple, variant_results) for breakdown_tuple in breakdown_tuples
        ]

        aggregated_variants = aggregate_variants_across_breakdowns(variant_results)

        return breakdown_results, aggregated_variants

    def _compute_breakdown_statistics(
        self,
        breakdown_tuple: tuple[str, ...],
        variant_results: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]],
    ) -> ExperimentBreakdownResult:
        """Compute statistics for a single breakdown combination."""
        breakdown_variants = [v for bv, v in variant_results if bv == breakdown_tuple]

        # Ensure all expected variants are present in this breakdown group
        # Some breakdown groups may not have data for all variants (e.g., no control users with specific browser)
        variants_present = {v.key for v in breakdown_variants}
        for expected_variant in self.variants:
            if expected_variant not in variants_present:
                # Add missing variant with zero stats to avoid "No control variant found" error
                breakdown_variants.append(
                    ExperimentStatsBase(
                        key=expected_variant,
                        number_of_samples=0,
                        sum=0,
                        sum_squares=0,
                    )
                )

        stats = self._calculate_statistics_for_variants(breakdown_variants)

        return ExperimentBreakdownResult(
            breakdown_value=list(breakdown_tuple),
            baseline=stats.baseline,
            variants=stats.variant_results,
        )

    def _add_missing_variants(
        self, variants: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]
    ) -> list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]:
        """
        Check if the variants configured in the experiment is seen in the collected data.
        If not, add them to the result set with values set to 0.
        Preserves the tuple structure with breakdown values.
        """
        variants_seen = [v.key for _, v in variants]

        has_breakdown = (
            self.metric.breakdownFilter is not None
            and self.metric.breakdownFilter.breakdowns
            and len(self.metric.breakdownFilter.breakdowns) > 0
        )

        # Type annotation required for empty list so mypy knows the expected element type:
        # list of tuples containing (breakdown_values, stats) where breakdown_values can be None
        variants_missing: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]] = []
        for key in self.variants:
            if key not in variants_seen:
                if has_breakdown:
                    # Extract all breakdown value combinations that exist in the results
                    breakdown_tuples = {bv for bv, _ in variants if bv is not None}
                    # Use extend to add MULTIPLE tuples - one for each breakdown combination
                    # Each missing variant needs to appear across ALL breakdown values to maintain consistency
                    variants_missing.extend(
                        [
                            (bv, ExperimentStatsBase(key=key, number_of_samples=0, sum=0, sum_squares=0))
                            for bv in breakdown_tuples
                        ]
                    )
                else:
                    # Use append to add a SINGLE tuple with None as the breakdown value
                    # Without breakdowns, we only need one entry per missing variant
                    variants_missing.append(
                        (None, ExperimentStatsBase(key=key, number_of_samples=0, sum=0, sum_squares=0))
                    )

        return variants + variants_missing

    def to_actors_query(self) -> ast.SelectQuery:
        """
        Generate actors query for experiment funnels with exposure filtering.

        This method builds an actors query that applies the SAME temporal filtering
        as the main experiment query by including exposure as step 0.

        Key differences from main query:
        - Returns individual users instead of aggregate statistics
        - Filters to specific step and variant
        - Includes matched recordings when requested

        The query structure mirrors the main experiment query:
        - Step 0: Exposure event (filters events to only those AFTER exposure)
        - Step 1-N: Metric events from funnel.series

        This ensures counts match between funnel visualization and PersonModal.
        """
        # Ensure actors_query is set
        if self.actors_query is None:
            raise ValidationError("actors_query must be set before calling to_actors_query()")

        # Only support funnel metrics for now
        if not isinstance(self.metric, ExperimentFunnelMetric):
            raise ValidationError("Actors query only supported for funnel experiment metrics")

        # Validate funnelStep
        funnel_step = self.actors_query.funnelStep
        if funnel_step is None:
            raise ValidationError("funnelStep is required for experiment actors query")

        num_metric_steps = len(self.metric.series)

        # Validate step range (same validation as before)
        if funnel_step == -1:
            # -1 would mean "dropped before first metric step" which is invalid
            # because we only query exposed users who are already past the exposure checkpoint
            # Build event names string (handle EventsNode, ActionsNode, and ExperimentDataWarehouseNode)
            from posthog.schema import ActionsNode, EventsNode

            event_names: list[str] = []
            for step in self.metric.series[:2]:
                if isinstance(step, EventsNode):
                    event_names.append(step.event or "All events")
                elif isinstance(step, ActionsNode):
                    event_names.append(f"Action {step.id}")
                else:  # ExperimentDataWarehouseNode
                    event_names.append(f"DW table {step.table_name}")

            metric_events_str = " → ".join(event_names)
            if len(self.metric.series) > 2:
                metric_events_str += " → ..."

            raise ValidationError(
                f"Cannot query drop-offs before the first metric step in experiment funnels. "
                f"Experiment funnel structure: [Exposure → {metric_events_str}]. "
                f"Drop-offs at funnelStep=-1 would mean 'exposed but never entered the funnel', "
                f"which cannot be queried through the actors API. "
                f"Valid drop-off steps: -2 (dropped after first metric step) to -{num_metric_steps + 1}."
            )

        if funnel_step == 0:
            raise ValidationError(
                "Funnel steps are 1-indexed. Step 0 does not exist. "
                f"Valid conversion steps: 1 (first metric step) to {num_metric_steps}."
            )

        if funnel_step < -1:
            max_drop_off = -(num_metric_steps + 1)
            if funnel_step < max_drop_off:
                raise ValidationError(
                    f"Invalid drop-off step {funnel_step} for experiment with {num_metric_steps} metric steps. "
                    f"Valid drop-off steps: -2 (dropped after first metric step) to {max_drop_off}."
                )

        if funnel_step > num_metric_steps:
            raise ValidationError(
                f"Invalid conversion step {funnel_step} for experiment with {num_metric_steps} metric steps. "
                f"Valid conversion steps: 1 (first metric step) to {num_metric_steps}."
            )

        # Extract exposure configuration from actors query
        # Fall back to experiment exposure_criteria if not provided
        from posthog.schema import ActionsNode, ExperimentEventExposureConfig

        exposure_config: ExperimentEventExposureConfig | ActionsNode
        if self.actors_query.exposureConfig is not None:
            exposure_config = self.actors_query.exposureConfig
        elif self.experiment.exposure_criteria and self.experiment.exposure_criteria.get("exposure_config"):
            from posthog.hogql_queries.experiments.experiment_query_builder import normalize_to_exposure_criteria

            criteria = normalize_to_exposure_criteria(self.experiment.exposure_criteria)
            if criteria and criteria.exposure_config:
                exposure_config = criteria.exposure_config
            else:
                # Default to $feature_flag_called
                exposure_config = ExperimentEventExposureConfig(event="$feature_flag_called", properties=[])
        else:
            # Default to $feature_flag_called
            exposure_config = ExperimentEventExposureConfig(event="$feature_flag_called", properties=[])

        # Get multiple variant handling
        if self.actors_query.multipleVariantHandling is not None:
            multiple_variant_handling = self.actors_query.multipleVariantHandling
        else:
            multiple_variant_handling = self.multiple_variant_handling

        # Get feature flag key
        if self.actors_query.featureFlagKey:
            feature_flag_key = self.actors_query.featureFlagKey
        else:
            feature_flag_key = self.feature_flag.key

        # Import builder here to avoid circular dependencies
        from posthog.hogql_queries.experiments.experiment_funnel_actors_query_builder import (
            ExperimentFunnelActorsQueryBuilder,
        )

        # Extract funnel_step_breakdown and ensure it's a simple type
        funnel_step_breakdown_raw = self.actors_query.funnelStepBreakdown
        if funnel_step_breakdown_raw is None:
            funnel_step_breakdown: str | int | float = ""
        elif isinstance(funnel_step_breakdown_raw, list):
            # If it's a list, take the first element
            funnel_step_breakdown = funnel_step_breakdown_raw[0] if funnel_step_breakdown_raw else ""
        else:
            funnel_step_breakdown = funnel_step_breakdown_raw

        # Add experiment-specific tags for monitoring and alerting
        metric_name = self.metric.name or get_default_metric_title(self.metric.model_dump())
        tag_queries(
            product=Product.EXPERIMENTS,
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            experiment_feature_flag_key=feature_flag_key,
            experiment_metric_uuid=self.metric.uuid,
            experiment_metric_name=metric_name,
            experiment_actors_query_step=funnel_step,
            experiment_actors_query_variant=str(funnel_step_breakdown) if funnel_step_breakdown else "",
            experiment_actors_query_includes_recordings=self.actors_query.includeRecordings or False,
        )

        # Build the actors query using the same infrastructure as main query
        builder = ExperimentFunnelActorsQueryBuilder(
            team=self.team,
            feature_flag_key=feature_flag_key,
            exposure_config=exposure_config,
            filter_test_accounts=self.experiment.exposure_criteria.get("filterTestAccounts", True)
            if self.experiment.exposure_criteria
            else False,
            multiple_variant_handling=multiple_variant_handling,
            variants=self.variants,
            date_range_query=self.date_range_query,
            entity_key=self.entity_key,
            metric=self.metric,
            funnel_step=funnel_step,
            funnel_step_breakdown=funnel_step_breakdown,
            include_recordings=self.actors_query.includeRecordings or False,
        )

        return builder.build_actors_query()

    def to_query(self) -> ast.SelectQuery:
        raise ValidationError(f"Cannot convert source query of type {self.query.metric.kind} to query")

    # Cache results for 24 hours
    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        return last_refresh + timedelta(hours=24)

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        payload["experiment_response_version"] = 2
        payload["stats_method"] = self.stats_method
        return payload

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        if not last_refresh:
            return True
        return (datetime.now(UTC) - last_refresh) > timedelta(hours=24)
