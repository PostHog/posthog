from typing import Optional, Union, cast

from django.utils import timezone

from posthog.schema import (
    ActionsNode,
    Breakdown,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentEventExposureConfig,
    ExperimentExposureCriteria,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricOutlierHandling,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    MultipleVariantHandling,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.experiments.base_query_utils import is_session_property_metric, validate_session_property
from posthog.hogql_queries.experiments.breakdown_injector import BreakdownInjector
from posthog.hogql_queries.experiments.cuped_config import CupedQueryConfig
from posthog.hogql_queries.experiments.experiment_exposure_query_builder import ExposureQueryBuilder
from posthog.hogql_queries.experiments.experiment_funnel_query_builder import FunnelQueryBuilder
from posthog.hogql_queries.experiments.experiment_metric_values import (
    build_conversion_window_predicate,
    build_conversion_window_predicate_for_events,
    build_metric_predicate,
    build_session_conversion_window_predicate,
    build_value_aggregation_expr,
    build_value_expr,
    get_conversion_window_seconds,
)
from posthog.hogql_queries.experiments.experiment_query_context import (
    ExperimentPrecomputationContext,
    ExperimentQueryContext,
)
from posthog.hogql_queries.experiments.experiment_retention_query_builder import RetentionQueryBuilder
from posthog.hogql_queries.experiments.exposure_query_logic import normalize_to_exposure_criteria
from posthog.hogql_queries.experiments.funnel_step_builder import FunnelStepBuilder
from posthog.hogql_queries.experiments.metric_source import MetricSourceInfo
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team


def get_exposure_config_params_for_builder(
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None],
) -> tuple[ExperimentEventExposureConfig | ActionsNode, MultipleVariantHandling, bool]:
    """Returns exposure-related parameters required by the query builder."""
    criteria = normalize_to_exposure_criteria(exposure_criteria)
    exposure_config: ExperimentEventExposureConfig | ActionsNode
    if criteria is None:
        exposure_config = ExperimentEventExposureConfig(event="$feature_flag_called", properties=[])
        filter_test_accounts = True
        multiple_variant_handling = MultipleVariantHandling.EXCLUDE
    else:
        if criteria.exposure_config is None:
            exposure_config = ExperimentEventExposureConfig(event="$feature_flag_called", properties=[])
        else:
            exposure_config = criteria.exposure_config
        filter_test_accounts = bool(criteria.filterTestAccounts) if criteria.filterTestAccounts is not None else True
        multiple_variant_handling = criteria.multiple_variant_handling or MultipleVariantHandling.EXCLUDE

    return (exposure_config, multiple_variant_handling, filter_test_accounts)


class ExperimentQueryBuilder:
    def __init__(
        self,
        team: Team,
        feature_flag_key: str,
        exposure_config: ExperimentEventExposureConfig | ActionsNode,
        filter_test_accounts: bool,
        multiple_variant_handling: MultipleVariantHandling,
        variants: list[str],
        date_range_query: QueryDateRange,
        entity_key: str,
        metric: Optional[
            ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric
        ] = None,
        breakdowns: list[Breakdown] | None = None,
        only_count_matured_users: bool = False,
        funnel_steps_data_disabled: bool = False,
        cuped_config: CupedQueryConfig | None = None,
    ):
        self.team = team
        self.metric = metric
        self.only_count_matured_users = only_count_matured_users
        self.funnel_steps_data_disabled = funnel_steps_data_disabled
        self.feature_flag_key = feature_flag_key
        self.variants = variants
        self.date_range_query = date_range_query
        self.entity_key = entity_key
        self.exposure_config = exposure_config
        self.filter_test_accounts = filter_test_accounts
        self.multiple_variant_handling = multiple_variant_handling
        self.breakdowns = breakdowns or []
        self.breakdown_injector = BreakdownInjector(self.breakdowns, metric) if metric else None
        self.preaggregation_job_ids: list[str] | None = None
        self.metric_events_preaggregation_job_ids: list[str] | None = None
        self.cuped_config = cuped_config or CupedQueryConfig()

        # Experiment-level invariants, gathered into a single frozen context for
        # later extracted modules to consume. Additive: every self.* attribute
        # above remains the source of truth for existing internal methods.
        self.context = ExperimentQueryContext(
            team=self.team,
            feature_flag_key=self.feature_flag_key,
            exposure_config=self.exposure_config,
            filter_test_accounts=self.filter_test_accounts,
            multiple_variant_handling=self.multiple_variant_handling,
            variants=tuple(self.variants),
            date_range_query=self.date_range_query,
            entity_key=self.entity_key,
            breakdowns=tuple(self.breakdowns),
            only_count_matured_users=self.only_count_matured_users,
            funnel_steps_data_disabled=self.funnel_steps_data_disabled,
            cuped_config=self.cuped_config,
        )

    # Experiment queries group by (variant, breakdown_values), so the row count is
    # bounded by num_variants × num_breakdown_values.  The HogQL executor injects
    # LIMIT 100 when no explicit limit is set, which silently truncates results for
    # high-cardinality breakdowns.  Set a generous explicit limit to prevent this.
    QUERY_RESULT_LIMIT = MAX_SELECT_RETURNED_ROWS

    def build_query(self, precomputation_context: ExperimentPrecomputationContext | None = None) -> ast.SelectQuery:
        """
        Main entry point. Returns complete query built from HogQL with placeholders.

        When ``precomputation_context`` is supplied, the precomputed job IDs are
        applied here so every internal method that reads ``self.*`` stays
        unchanged. Job IDs can only be supplied at build time because the builder
        itself generates the precompute queries before any job IDs exist.
        """
        if precomputation_context is not None:
            self.preaggregation_job_ids = precomputation_context.exposure_job_ids
            self.metric_events_preaggregation_job_ids = precomputation_context.metric_events_job_ids

        assert self.metric is not None, "metric is required for build_query()"
        match self.metric:
            case ExperimentFunnelMetric():
                query = self._build_funnel_query()
            case ExperimentMeanMetric():
                query = self._build_mean_query()
            case ExperimentRatioMetric():
                query = self._build_ratio_query()
            case ExperimentRetentionMetric():
                query = self._build_retention_query()
            case _:
                raise NotImplementedError(
                    f"Only funnel, mean, ratio, and retention metrics are supported. Got {type(self.metric)}"
                )

        query.limit = ast.Constant(value=self.QUERY_RESULT_LIMIT)
        return query

    def _exposure_query_builder(self) -> ExposureQueryBuilder:
        """Construct an ExposureQueryBuilder from the current builder state.

        Built fresh per call so it picks up the current ``preaggregation_job_ids``
        (only known at build time).
        """
        return ExposureQueryBuilder(
            context=self.context,
            breakdown_injector=self.breakdown_injector,
            maturity_having_builder=self._build_maturity_having_clause,
            preaggregation_job_ids=self.preaggregation_job_ids,
        )

    def _funnel_query_builder(self) -> FunnelQueryBuilder:
        """Construct a FunnelQueryBuilder backed by the current builder state.

        Built fresh per call so it picks up the current precomputation job IDs
        (only known at build time).
        """
        return FunnelQueryBuilder(self)

    def _retention_query_builder(self) -> RetentionQueryBuilder:
        """Construct a RetentionQueryBuilder backed by the current builder state."""
        return RetentionQueryBuilder(self)

    def get_exposure_timeseries_query(self) -> ast.SelectQuery:
        """
        Returns a query for exposure timeseries data.

        Generates daily exposure counts per variant, counting each entity
        only once on their first exposure day.

        Returns:
            SelectQuery with columns: day, variant, exposed_count
        """
        return self._exposure_query_builder().timeseries_query()

    def get_daily_exposures_from_precomputed(self, job_ids: list[str]) -> ast.SelectQuery:
        """
        Reads from the precomputed table and aggregates into day/variant/count.
        Used by the Exposures tab in the experiment UI.
        """
        return self._exposure_query_builder().daily_exposures_from_precomputed(job_ids)

    def _get_conversion_window_seconds(self) -> int:
        """
        Returns the conversion window in seconds for the current metric.
        Returns 0 if no conversion window is configured.
        """
        assert self.metric is not None, "metric is required for _get_conversion_window_seconds()"
        return get_conversion_window_seconds(self.metric)

    def _get_maturity_window_seconds(self) -> int:
        """
        Returns the maturity window in seconds for non-retention metrics.
        Retention metrics use _get_retention_maturity_seconds and apply maturity
        in the start_events CTE, anchored on start_event timestamp.
        """
        return self._get_conversion_window_seconds()

    def _get_retention_maturity_seconds(self) -> int:
        """
        Returns the maturity window in seconds for retention metrics.
        Equals retention_window_end converted to seconds; conversion_window does
        not contribute because retention maturity is anchored on start_event.
        """
        return self._retention_query_builder().get_retention_maturity_seconds()

    def _build_maturity_having_clause(self, timestamp_expr: str = "timestamp") -> Optional[ast.Expr]:
        """
        Returns a HAVING clause expression to filter out users whose conversion window
        hasn't elapsed yet, or None if the feature is not enabled.

        Retention metrics handle maturity separately in their own start_events CTE
        via _build_retention_maturity_having_clause; this function intentionally
        returns None for them.
        """
        if self.metric is None:
            return None
        if isinstance(self.metric, ExperimentRetentionMetric):
            return None
        if not self.only_count_matured_users:
            return None

        maturity_seconds = self._get_maturity_window_seconds()
        if maturity_seconds == 0:
            return None

        now = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        return parse_expr(
            f"max({timestamp_expr}) + toIntervalSecond({{maturity_seconds}}) <= toDateTime({{now}}, 'UTC')",
            placeholders={
                "maturity_seconds": ast.Constant(value=maturity_seconds),
                "now": ast.Constant(value=now),
            },
        )

    def _build_retention_maturity_having_clause(self) -> Optional[ast.Expr]:
        """
        Returns a HAVING clause for the retention query's start_events CTE that
        filters out users whose retention window has not yet fully elapsed since
        their start_event.

        Anchored on the user's start_event timestamp (min or max of start event
        timestamps, depending on start_handling).
        """
        return self._retention_query_builder().build_retention_maturity_having_clause()

    def _build_funnel_query(self) -> ast.SelectQuery:
        """
        Builds query for funnel metrics.
        Dispatches to optimized (single-scan) or legacy (double-scan) path.
        """
        return self._funnel_query_builder().build_funnel_query()

    def _should_use_optimized_funnel_query(self) -> bool:
        """
        Returns True when the optimized single-scan funnel query should be used.
        The legacy path is kept for precomputed exposures, where the exposures CTE
        reads from a cheap preaggregated table (no double-scan penalty).

        Also routes to legacy path for DW funnels, which use UNION ALL pattern
        only implemented in the legacy path.
        """
        return self._funnel_query_builder().should_use_optimized_funnel_query()

    def _build_funnel_query_legacy(self) -> ast.SelectQuery:
        """
        3-CTE funnel query: exposures, metric_events, entity_metrics.
        Called "legacy" because it predates the single-scan optimized path,
        but this is the primary path for precomputed queries — both exposures
        and metric_events CTEs can read from precomputed tables here.

        Supports two patterns:
        1. Events-only: Single query with boolean step columns
        2. With DW steps: UNION ALL pattern with separate subqueries per source
        """
        return self._funnel_query_builder().build_funnel_query_legacy()

    def _build_funnel_query_optimized(self) -> ast.SelectQuery:
        """
        Optimized funnel query: eliminates the second events table scan and the
        intermediate JOIN. Uses 2 CTEs for ordered funnels, 3 for unordered:

        Ordered:   base_events -> entity_metrics -> final SELECT
        Unordered: base_events -> first_exposures -> entity_metrics -> final SELECT

        base_events: single scan of events, computes step_0/step_1/variant_value inline
        first_exposures: (unordered only) min exposure time per entity for temporal filtering
        entity_metrics: GROUP BY entity_id, conditional aggregation for variant, funnel UDF
        """
        return self._funnel_query_builder().build_funnel_query_optimized()

    def _get_session_property_ctes(self) -> str:
        """
        Returns CTEs for session property metrics with proper deduplication.

        Session properties require special handling to avoid the multiplication bug:
        - Without deduplication: each event in a session contributes the full session value
        - With deduplication: each session contributes exactly once

        Pattern:
        1. metric_events_by_session: GROUP BY $session_id, get any(session.$property)
        2. metric_events: Join with exposures, filter by temporal ordering
        3. entity_metrics: Aggregate across sessions per entity
        """
        assert isinstance(self.metric, ExperimentMeanMetric)
        assert isinstance(self.metric.source, (ActionsNode, EventsNode))

        session_property = validate_session_property(self.metric.source)

        return f"""
            exposures AS (
                {{exposure_select_query}}
            ),

            -- Layer 1: Deduplicate within sessions
            -- Each session contributes exactly one value regardless of event count
            metric_events_by_session AS (
                SELECT
                    {{entity_key}} AS entity_id,
                    `$session_id` AS session_id,
                    any(session.`{session_property}`) AS session_value,
                    min(timestamp) AS first_event_timestamp
                FROM events
                WHERE {{metric_predicate}}
                    AND `$session_id` IS NOT NULL
                    AND `$session_id` != ''
                GROUP BY {{entity_key}}, `$session_id`
            ),

            -- Layer 2: Join with exposures, filter by temporal ordering
            metric_events AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    toFloat(coalesce(metric_events_by_session.session_value, 0)) AS value,
                    metric_events_by_session.session_id AS session_id
                FROM exposures
                INNER JOIN metric_events_by_session
                    ON exposures.entity_id = metric_events_by_session.entity_id
                    AND metric_events_by_session.first_event_timestamp >= exposures.first_exposure_time
                    AND {{session_conversion_window_predicate}}
            ),

            -- Layer 3: Aggregate across sessions per entity
            entity_metrics AS (
                SELECT
                    entity_id,
                    variant,
                    {{value_agg}} AS value
                FROM metric_events
                GROUP BY entity_id, variant
            )
        """

    def _get_mean_query_common_ctes(self) -> str:
        """
        Returns the common CTEs used by both regular and winsorized mean queries.
        Supports both regular events and data warehouse sources.
        """
        assert isinstance(self.metric, ExperimentMeanMetric)

        # Check if this is a session property metric - use special CTE structure
        if isinstance(self.metric.source, (ActionsNode, EventsNode)) and is_session_property_metric(self.metric.source):
            return self._get_session_property_ctes()

        # Use MetricSourceInfo abstraction for source metadata
        source_info = MetricSourceInfo.from_source(self.metric.source, entity_key=self.entity_key)

        # Determine join condition based on source type
        if source_info.kind == "datawarehouse":
            join_condition = "{join_condition}"
        else:
            join_condition = "exposures.entity_id = metric_events.entity_id"

        if self.cuped_config.enabled:
            join_window_predicate = "({conversion_window_predicate} OR {cuped_pre_window_predicate})"
            entity_metric_selects = """
                    {value_agg} AS value,
                    {covariate_value_agg} AS covariate_value"""
        else:
            join_window_predicate = "{conversion_window_predicate}"
            entity_metric_selects = """
                    {value_agg} AS value"""

        return f"""
            exposures AS (
                {{exposure_select_query}}
            ),

            metric_events AS (
                SELECT
                    {{entity_key}} AS entity_id,
                    {{metric_timestamp_field}} AS timestamp,
                    {{value_expr}} AS value
                    -- breakdown columns added programmatically below
                FROM {{metric_table}}
                WHERE {{metric_predicate}}
            ),

            entity_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
{entity_metric_selects}
                    -- breakdown columns added programmatically below
                FROM exposures
                LEFT JOIN metric_events ON {join_condition}
                    AND {join_window_predicate}
                GROUP BY exposures.entity_id, exposures.variant
                -- breakdown columns added programmatically below
            )
        """

    def _get_mean_query_common_placeholders(self) -> dict:
        """
        Returns the common placeholders used by both regular and winsorized mean queries.
        Supports both regular events and data warehouse sources.
        """
        assert isinstance(self.metric, ExperimentMeanMetric)

        # Check if this is a session property metric - use different placeholders
        is_session_property = isinstance(self.metric.source, (ActionsNode, EventsNode)) and is_session_property_metric(
            self.metric.source
        )

        if is_session_property:
            return self._get_session_property_placeholders()

        # Use MetricSourceInfo abstraction for source metadata
        source_info = MetricSourceInfo.from_source(self.metric.source, entity_key=self.entity_key)

        # Build exposure query with exposure_identifier for data warehouse
        exposure_query = self._get_exposure_query()
        if source_info.kind == "datawarehouse":
            assert isinstance(self.metric.source, ExperimentDataWarehouseNode)
            events_join_key_parts = cast(list[str | int], self.metric.source.events_join_key.split("."))

            # Use argMin to pick one exposure_identifier per entity_id (from first exposure)
            # This prevents fan-out when a user has multiple exposures with different join key values
            exposure_query.select.append(
                ast.Alias(
                    alias="exposure_identifier",
                    expr=ast.Call(
                        name="argMin",
                        args=[ast.Field(chain=events_join_key_parts), ast.Field(chain=["timestamp"])],
                    ),
                )
            )
            # Do NOT add to GROUP BY - that would cause fan-out when join key varies across exposures

        metric_predicate = self._build_metric_predicate(
            table_alias=source_info.table_name,
            cuped_lookback_days=self.cuped_config.lookback_days if self.cuped_config.enabled else None,
        )
        conversion_window_predicate = self._build_conversion_window_predicate()

        placeholders: dict = {
            "exposure_select_query": exposure_query,
            "entity_key": source_info.entity_key,
            "metric_timestamp_field": ast.Field(chain=[source_info.timestamp_field]),
            "metric_table": ast.Field(chain=[source_info.table_name]),
            "metric_predicate": metric_predicate,
            "value_expr": self._build_value_expr(),
            "value_agg": self._build_value_aggregation_expr(
                value_expr=self._build_windowed_metric_value_expr(conversion_window_predicate)
                if self.cuped_config.enabled
                else None
            ),
            "conversion_window_predicate": conversion_window_predicate,
        }

        if self.cuped_config.enabled:
            cuped_pre_window_predicate = self._build_cuped_pre_window_predicate()
            placeholders["cuped_pre_window_predicate"] = cuped_pre_window_predicate
            placeholders["covariate_value_agg"] = self._build_value_aggregation_expr(
                value_expr=self._build_windowed_metric_value_expr(cuped_pre_window_predicate)
            )

        # Add join condition for data warehouse
        if source_info.kind == "datawarehouse":
            placeholders["join_condition"] = parse_expr(
                "toString(exposures.exposure_identifier) = toString(metric_events.entity_id)"
            )

        return placeholders

    def _get_session_property_placeholders(self) -> dict:
        """
        Returns placeholders specific to session property metrics.
        Session properties use a different CTE structure with deduplication per session.
        """
        assert isinstance(self.metric, ExperimentMeanMetric)

        exposure_query = self._get_exposure_query()

        return {
            "exposure_select_query": exposure_query,
            "entity_key": parse_expr(self.entity_key),
            "metric_predicate": self._build_metric_predicate(table_alias="events"),
            "value_agg": self._build_value_aggregation_expr(),
            "session_conversion_window_predicate": self._build_session_conversion_window_predicate(),
        }

    def _build_mean_query(self) -> ast.SelectQuery:
        """
        Builds query for mean metrics (count, sum, avg, etc.)
        """
        assert isinstance(self.metric, ExperimentMeanMetric)

        # Check if we need to apply winsorization (outlier handling)
        needs_winsorization = (
            self.metric.lower_bound_percentile is not None or self.metric.upper_bound_percentile is not None
        )

        if needs_winsorization:
            return self._build_mean_query_with_winsorization()

        common_ctes = self._get_mean_query_common_ctes()
        cuped_selects = (
            """,
                sum(entity_metrics.covariate_value) AS covariate_sum,
                sum(power(entity_metrics.covariate_value, 2)) AS covariate_sum_squares,
                sum(entity_metrics.value * entity_metrics.covariate_value) AS covariate_sum_product"""
            if self.cuped_config.enabled
            else ""
        )

        query = parse_select(
            f"""
            WITH {common_ctes}

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                sum(entity_metrics.value) AS total_sum,
                sum(power(entity_metrics.value, 2)) AS total_sum_of_squares{cuped_selects}
                -- breakdown columns added programmatically below
            FROM entity_metrics
            GROUP BY entity_metrics.variant
            -- breakdown columns added programmatically below
            """,
            placeholders=self._get_mean_query_common_placeholders(),
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns into the query AST
        if self.breakdown_injector:
            self.breakdown_injector.inject_mean_breakdown_columns(query, final_cte_name="entity_metrics")

        return query

    def _build_mean_query_with_winsorization(self) -> ast.SelectQuery:
        """
        Builds query for mean metrics with winsorization (outlier handling).
        This clamps entity-level values to percentile-based bounds.
        """
        assert isinstance(self.metric, ExperimentMeanMetric)

        # Build lower bound expression
        if self.metric.lower_bound_percentile is not None:
            lower_bound_expr = parse_expr(
                "quantileExact({level})(entity_metrics.value)",
                placeholders={"level": ast.Constant(value=self.metric.lower_bound_percentile)},
            )
        else:
            lower_bound_expr = parse_expr("min(entity_metrics.value)")

        # Build upper bound expression
        if self.metric.upper_bound_percentile is not None:
            # Handle ignore_zeros flag for upper bound calculation
            if getattr(self.metric, "ignore_zeros", False):
                upper_bound_expr = parse_expr(
                    "quantileExact({level})(if(entity_metrics.value != 0, entity_metrics.value, null))",
                    placeholders={"level": ast.Constant(value=self.metric.upper_bound_percentile)},
                )
            else:
                upper_bound_expr = parse_expr(
                    "quantileExact({level})(entity_metrics.value)",
                    placeholders={"level": ast.Constant(value=self.metric.upper_bound_percentile)},
                )
        else:
            upper_bound_expr = parse_expr("max(entity_metrics.value)")

        common_ctes = self._get_mean_query_common_ctes()
        placeholders = self._get_mean_query_common_placeholders()
        winsorized_cuped_select = (
            """,
                    entity_metrics.covariate_value AS covariate_value"""
            if self.cuped_config.enabled
            else ""
        )
        cuped_selects = (
            """,
                sum(winsorized_entity_metrics.covariate_value) AS covariate_sum,
                sum(power(winsorized_entity_metrics.covariate_value, 2)) AS covariate_sum_squares,
                sum(winsorized_entity_metrics.value * winsorized_entity_metrics.covariate_value) AS covariate_sum_product"""
            if self.cuped_config.enabled
            else ""
        )

        # Add winsorization-specific placeholders
        placeholders["lower_bound"] = lower_bound_expr
        placeholders["upper_bound"] = upper_bound_expr

        query = parse_select(
            f"""
            WITH {common_ctes},

            percentiles AS (
                SELECT
                    {{lower_bound}} AS lower_bound,
                    {{upper_bound}} AS upper_bound
                    -- breakdown columns added programmatically below
                FROM entity_metrics
                -- GROUP BY added programmatically below if breakdowns exist
            ),

            winsorized_entity_metrics AS (
                SELECT
                    entity_metrics.entity_id AS entity_id,
                    entity_metrics.variant AS variant,
                    least(greatest(percentiles.lower_bound, entity_metrics.value), percentiles.upper_bound) AS value{winsorized_cuped_select}
                    -- breakdown columns added programmatically below
                FROM entity_metrics
                CROSS JOIN percentiles
                -- JOIN conditions added programmatically below if breakdowns exist
            )

            SELECT
                winsorized_entity_metrics.variant AS variant,
                count(winsorized_entity_metrics.entity_id) AS num_users,
                sum(winsorized_entity_metrics.value) AS total_sum,
                sum(power(winsorized_entity_metrics.value, 2)) AS total_sum_of_squares{cuped_selects}
                -- breakdown columns added programmatically below
            FROM winsorized_entity_metrics
            GROUP BY winsorized_entity_metrics.variant
            -- breakdown columns added programmatically below
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns into the query AST
        if self.breakdown_injector:
            self.breakdown_injector.inject_mean_breakdown_columns(query, final_cte_name="winsorized_entity_metrics")

        return query

    def _build_ratio_query(self) -> ast.SelectQuery:
        """
        Builds query for ratio metrics.

        Dispatches to the winsorized variant when outlier handling is configured for
        either the numerator or the denominator.
        """
        assert isinstance(self.metric, ExperimentRatioMetric)

        if self._ratio_needs_winsorization():
            return self._build_ratio_query_with_winsorization()

        common_ctes, placeholders = self._get_ratio_query_common()

        query = parse_select(
            f"""
            WITH {common_ctes}

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                sum(entity_metrics.numerator_value) AS total_sum,
                sum(power(entity_metrics.numerator_value, 2)) AS total_sum_of_squares,
                sum(entity_metrics.denominator_value) AS denominator_sum,
                sum(power(entity_metrics.denominator_value, 2)) AS denominator_sum_squares,
                sum(entity_metrics.numerator_value * entity_metrics.denominator_value) AS numerator_denominator_sum_product
                -- breakdown columns added programmatically below
            FROM entity_metrics
            GROUP BY entity_metrics.variant
            -- breakdown columns added programmatically below
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns into the query AST
        if self.breakdown_injector:
            self.breakdown_injector.inject_ratio_breakdown_columns(query)

        return query

    def _ratio_needs_winsorization(self) -> bool:
        """Whether either component of a ratio metric has outlier handling configured."""
        assert isinstance(self.metric, ExperimentRatioMetric)
        for outlier_handling in (
            self.metric.numerator_outlier_handling,
            self.metric.denominator_outlier_handling,
        ):
            if outlier_handling is not None and (
                outlier_handling.lower_bound_percentile is not None
                or outlier_handling.upper_bound_percentile is not None
            ):
                return True
        return False

    def _build_winsorization_bound_exprs(
        self,
        outlier_handling: ExperimentMetricOutlierHandling | None,
        value_field: str,
    ) -> tuple[ast.Expr, ast.Expr]:
        """
        Build (lower_bound, upper_bound) expressions over entity_metrics.<value_field>.

        When a bound is not configured the threshold falls back to min()/max() so the
        least(greatest(...)) clamp becomes a no-op for that side. This lets the numerator
        and denominator be capped independently — a binomial denominator simply leaves its
        outlier handling unset and is never clamped.

        value_field is an internal column name (numerator_value / denominator_value), never
        user input, so interpolating it into the expression string is safe.
        """
        lower_pct = outlier_handling.lower_bound_percentile if outlier_handling else None
        upper_pct = outlier_handling.upper_bound_percentile if outlier_handling else None
        ignore_zeros = bool(outlier_handling.ignore_zeros) if outlier_handling else False

        if lower_pct is not None:
            lower_bound_expr = parse_expr(
                f"quantileExact({{level}})(entity_metrics.{value_field})",
                placeholders={"level": ast.Constant(value=lower_pct)},
            )
        else:
            lower_bound_expr = parse_expr(f"min(entity_metrics.{value_field})")

        if upper_pct is not None:
            if ignore_zeros:
                upper_bound_expr = parse_expr(
                    f"quantileExact({{level}})(if(entity_metrics.{value_field} != 0, entity_metrics.{value_field}, null))",
                    placeholders={"level": ast.Constant(value=upper_pct)},
                )
            else:
                upper_bound_expr = parse_expr(
                    f"quantileExact({{level}})(entity_metrics.{value_field})",
                    placeholders={"level": ast.Constant(value=upper_pct)},
                )
        else:
            upper_bound_expr = parse_expr(f"max(entity_metrics.{value_field})")

        return lower_bound_expr, upper_bound_expr

    def _build_ratio_query_with_winsorization(self) -> ast.SelectQuery:
        """
        Builds query for ratio metrics with winsorization (outlier handling).

        The numerator and denominator are capped independently, each as if it were its own
        mean metric: percentile thresholds are computed separately for each component (pooled
        across all variations) and the per-entity numerator and denominator values are clamped
        against their own bounds. The capped components flow into the same aggregate columns
        (including the cross-product) so the delta-method variance stays consistent with the
        capped point estimate.
        """
        assert isinstance(self.metric, ExperimentRatioMetric)

        common_ctes, placeholders = self._get_ratio_query_common()

        num_lower_bound, num_upper_bound = self._build_winsorization_bound_exprs(
            self.metric.numerator_outlier_handling, "numerator_value"
        )
        denom_lower_bound, denom_upper_bound = self._build_winsorization_bound_exprs(
            self.metric.denominator_outlier_handling, "denominator_value"
        )

        placeholders["numerator_lower_bound"] = num_lower_bound
        placeholders["numerator_upper_bound"] = num_upper_bound
        placeholders["denominator_lower_bound"] = denom_lower_bound
        placeholders["denominator_upper_bound"] = denom_upper_bound

        query = parse_select(
            f"""
            WITH {common_ctes},

            percentiles AS (
                SELECT
                    {{numerator_lower_bound}} AS numerator_lower_bound,
                    {{numerator_upper_bound}} AS numerator_upper_bound,
                    {{denominator_lower_bound}} AS denominator_lower_bound,
                    {{denominator_upper_bound}} AS denominator_upper_bound
                    -- breakdown columns added programmatically below
                FROM entity_metrics
                -- GROUP BY added programmatically below if breakdowns exist
            ),

            winsorized_entity_metrics AS (
                SELECT
                    entity_metrics.entity_id AS entity_id,
                    entity_metrics.variant AS variant,
                    least(greatest(percentiles.numerator_lower_bound, entity_metrics.numerator_value), percentiles.numerator_upper_bound) AS numerator_value,
                    least(greatest(percentiles.denominator_lower_bound, entity_metrics.denominator_value), percentiles.denominator_upper_bound) AS denominator_value
                    -- breakdown columns added programmatically below
                FROM entity_metrics
                CROSS JOIN percentiles
                -- JOIN conditions added programmatically below if breakdowns exist
            )

            SELECT
                winsorized_entity_metrics.variant AS variant,
                count(winsorized_entity_metrics.entity_id) AS num_users,
                sum(winsorized_entity_metrics.numerator_value) AS total_sum,
                sum(power(winsorized_entity_metrics.numerator_value, 2)) AS total_sum_of_squares,
                sum(winsorized_entity_metrics.denominator_value) AS denominator_sum,
                sum(power(winsorized_entity_metrics.denominator_value, 2)) AS denominator_sum_squares,
                sum(winsorized_entity_metrics.numerator_value * winsorized_entity_metrics.denominator_value) AS numerator_denominator_sum_product
                -- breakdown columns added programmatically below
            FROM winsorized_entity_metrics
            GROUP BY winsorized_entity_metrics.variant
            -- breakdown columns added programmatically below
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns into the query AST
        if self.breakdown_injector:
            self.breakdown_injector.inject_ratio_breakdown_columns(query, winsorized=True)

        return query

    def _get_ratio_query_common(self) -> tuple[str, dict[str, ast.Expr]]:
        """
        Builds the shared CTE chain and placeholders for ratio metric queries.

        Optimized structure using pre-aggregation to reduce join operations:
        - exposures: all exposures with variant assignment (with exposure_identifier for data warehouse)
        - numerator_events / denominator_events: events for each component with value
        - numerator_agg / denominator_agg: per-entity aggregates joined to exposures
        - entity_metrics: single row per entity carrying numerator_value and denominator_value

        This approach reduces memory pressure by joining exposures to events only once
        per component instead of fanning out the raw event rows.
        """
        assert isinstance(self.metric, ExperimentRatioMetric)

        # Use MetricSourceInfo abstraction for both numerator and denominator
        num_source_info = MetricSourceInfo.from_source(self.metric.numerator, entity_key=self.entity_key)
        denom_source_info = MetricSourceInfo.from_source(self.metric.denominator, entity_key=self.entity_key)

        # Extract field names for numerator
        num_table = num_source_info.table_name
        num_entity_field = num_source_info.entity_key
        num_timestamp_field = num_source_info.timestamp_field

        # Extract field names for denominator
        denom_table = denom_source_info.table_name
        denom_entity_field = denom_source_info.entity_key
        denom_timestamp_field = denom_source_info.timestamp_field

        # Build exposure query with conditional exposure_identifier(s)
        exposure_query = self._get_exposure_query()
        if num_source_info.kind == "datawarehouse" or denom_source_info.kind == "datawarehouse":
            # Add exposure_identifier fields for data warehouse joins
            # Support different join keys for numerator and denominator
            if num_source_info.kind == "datawarehouse":
                num_source = cast(ExperimentDataWarehouseNode, self.metric.numerator)
                num_join_key_parts = cast(list[str | int], num_source.events_join_key.split("."))

                # Use argMin to pick one exposure_identifier per entity_id (from first exposure)
                # This prevents fan-out when a user has multiple exposures with different join key values
                exposure_query.select.append(
                    ast.Alias(
                        alias="exposure_identifier_num",
                        expr=ast.Call(
                            name="argMin",
                            args=[ast.Field(chain=num_join_key_parts), ast.Field(chain=["timestamp"])],
                        ),
                    )
                )
                # Do NOT add to GROUP BY - that would cause fan-out when join key varies across exposures

            if denom_source_info.kind == "datawarehouse":
                denom_source = cast(ExperimentDataWarehouseNode, self.metric.denominator)
                denom_join_key_parts = cast(list[str | int], denom_source.events_join_key.split("."))

                # Use argMin to pick one exposure_identifier per entity_id (from first exposure)
                # This prevents fan-out when a user has multiple exposures with different join key values
                exposure_query.select.append(
                    ast.Alias(
                        alias="exposure_identifier_denom",
                        expr=ast.Call(
                            name="argMin",
                            args=[ast.Field(chain=denom_join_key_parts), ast.Field(chain=["timestamp"])],
                        ),
                    )
                )
                # Do NOT add to GROUP BY - that would cause fan-out when join key varies across exposures

        # Build join conditions for pre-aggregation CTEs based on DW scenario
        if num_source_info.kind == "datawarehouse":
            num_preagg_join = "toString(exposures.exposure_identifier_num) = toString(numerator_events.entity_id)"
        else:
            num_preagg_join = "exposures.entity_id = numerator_events.entity_id"

        if denom_source_info.kind == "datawarehouse":
            denom_preagg_join = "toString(exposures.exposure_identifier_denom) = toString(denominator_events.entity_id)"
        else:
            denom_preagg_join = "exposures.entity_id = denominator_events.entity_id"

        # Pre-aggregation approach: aggregate events per entity_id FIRST, then join
        # This dramatically reduces memory usage by avoiding large intermediate result sets
        # Memory impact: 471M rows → ~2M rows in joins
        common_ctes = f"""
            exposures AS (
                {{exposure_select_query}}
            ),

            numerator_events AS (
                SELECT
                    {{num_entity_key}} AS entity_id,
                    {{num_timestamp_field}} AS timestamp,
                    {{numerator_value_expr}} AS value
                FROM {{num_table}}
                WHERE {{numerator_predicate}}
            ),

            denominator_events AS (
                SELECT
                    {{denom_entity_key}} AS entity_id,
                    {{denom_timestamp_field}} AS timestamp,
                    {{denominator_value_expr}} AS value
                FROM {{denom_table}}
                WHERE {{denominator_predicate}}
            ),

            numerator_agg AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    {{numerator_agg}} AS value
                FROM numerator_events
                JOIN exposures ON {num_preagg_join}
                WHERE {{numerator_conversion_window}}
                GROUP BY exposures.entity_id
            ),

            denominator_agg AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    {{denominator_agg}} AS value
                FROM denominator_events
                JOIN exposures ON {denom_preagg_join}
                WHERE {{denominator_conversion_window}}
                GROUP BY exposures.entity_id
            ),

            entity_metrics AS (
                SELECT
                    exposures.variant AS variant,
                    exposures.entity_id AS entity_id,
                    any(coalesce(numerator_agg.value, 0)) AS numerator_value,
                    any(coalesce(denominator_agg.value, 0)) AS denominator_value
                    -- breakdown columns added programmatically below
                FROM exposures
                LEFT JOIN numerator_agg ON exposures.entity_id = numerator_agg.entity_id
                LEFT JOIN denominator_agg ON exposures.entity_id = denominator_agg.entity_id
                GROUP BY exposures.variant, exposures.entity_id
                -- breakdown columns added programmatically below
            )
        """

        placeholders: dict[str, ast.Expr] = {
            "exposure_select_query": exposure_query,
            "num_entity_key": num_entity_field,
            "denom_entity_key": denom_entity_field,
            "num_timestamp_field": ast.Field(chain=[num_timestamp_field]),
            "num_table": ast.Field(chain=[num_table]),
            "denom_timestamp_field": ast.Field(chain=[denom_timestamp_field]),
            "denom_table": ast.Field(chain=[denom_table]),
            "numerator_predicate": self._build_metric_predicate(source=self.metric.numerator, table_alias=num_table),
            "numerator_value_expr": self._build_value_expr(source=self.metric.numerator),
            "numerator_agg": self._build_value_aggregation_expr(
                source=self.metric.numerator, events_alias="numerator_events", column_name="value"
            ),
            "numerator_conversion_window": self._build_conversion_window_predicate_for_events("numerator_events"),
            "denominator_predicate": self._build_metric_predicate(
                source=self.metric.denominator, table_alias=denom_table
            ),
            "denominator_value_expr": self._build_value_expr(source=self.metric.denominator),
            "denominator_agg": self._build_value_aggregation_expr(
                source=self.metric.denominator, events_alias="denominator_events", column_name="value"
            ),
            "denominator_conversion_window": self._build_conversion_window_predicate_for_events("denominator_events"),
        }

        return common_ctes, placeholders

    def _build_conversion_window_predicate(self) -> ast.Expr:
        """
        Build the predicate for limiting metric events to the conversion window for the user.
        Uses "metric_events" as the events alias.
        """
        return build_conversion_window_predicate(self._get_conversion_window_seconds())

    def _build_session_conversion_window_predicate(self) -> ast.Expr:
        """
        Build the predicate for limiting session metric events to the conversion window.
        Uses first_event_timestamp from metric_events_by_session for temporal filtering.
        """
        return build_session_conversion_window_predicate(self._get_conversion_window_seconds())

    def _build_conversion_window_predicate_for_events(self, events_alias: str) -> ast.Expr:
        """
        Build the predicate for limiting metric events to the conversion window for the user.
        Parameterized to support different event table aliases (for ratio metrics).
        """
        return build_conversion_window_predicate_for_events(events_alias, self._get_conversion_window_seconds())

    def _build_cuped_pre_window_predicate(
        self,
        events_alias: str = "metric_events",
        exposure_alias: str = "exposures",
    ) -> ast.Expr:
        return parse_expr(
            f"""
            {events_alias}.timestamp >= {exposure_alias}.first_exposure_time - toIntervalDay({{lookback_days}})
            AND {events_alias}.timestamp < {exposure_alias}.first_exposure_time
            """,
            placeholders={"lookback_days": ast.Constant(value=self.cuped_config.lookback_days)},
        )

    def _build_windowed_metric_value_expr(
        self, window_predicate: ast.Expr, events_alias: str = "metric_events"
    ) -> ast.Expr:
        return parse_expr(
            "if({window_predicate}, {metric_value}, NULL)",
            placeholders={
                "window_predicate": window_predicate,
                "metric_value": ast.Field(chain=[events_alias, "value"]),
            },
        )

    def _build_funnel_covariate_value_expr(
        self,
        *,
        events_alias: str,
        last_step_index: int,
        exposure_alias: str,
    ) -> ast.Expr:
        """
        Per-entity binary covariate for funnel CUPED: 1 if the entity fired the
        funnel's last step inside the pre-exposure window, else 0.

        The covariate has to be binary to keep the same Bernoulli scale as the
        post-window proportion metric, and aligns with the example pattern of
        treating the conversion event as both the metric and the covariate.
        """
        return parse_expr(
            f"coalesce(maxIf(1, {events_alias}.step_{last_step_index} = 1 AND {{pre_window}}), 0)",
            placeholders={"pre_window": self._build_cuped_pre_window_predicate(events_alias, exposure_alias)},
        )

    def _build_funnel_cuped_aggregation_aliases(self, last_step_index: int) -> list[ast.Expr]:
        """
        Outer-SELECT aliases that aggregate the per-entity covariate into the
        sums consumed by `cuped_adjust`. The cross-product term multiplies the
        user-level conversion indicator (value.1 = last_step_index) with the
        binary covariate.
        """
        return [
            parse_expr("sum(entity_metrics.covariate_value) AS covariate_sum"),
            parse_expr("sum(power(entity_metrics.covariate_value, 2)) AS covariate_sum_squares"),
            parse_expr(
                "sum(if(entity_metrics.value.1 = {n}, 1, 0) * entity_metrics.covariate_value) AS covariate_sum_product",
                placeholders={"n": ast.Constant(value=last_step_index)},
            ),
        ]

    def _inject_funnel_covariate_into_entity_metrics(
        self,
        query: ast.SelectQuery,
        *,
        events_alias: str,
        last_step_index: int,
        exposure_alias: str,
    ) -> None:
        """
        Adds `covariate_value` to the entity_metrics CTE, plus the aggregation
        aliases (`covariate_sum`, `covariate_sum_squares`, `covariate_sum_product`)
        to the outer SELECT.

        Asserts the expected `entity_metrics` CTE shape: this method is called
        right after the funnel SELECT is parsed in this same builder, so the
        shape is an invariant — a violation means the SQL above changed without
        updating CUPED, and we want a loud failure rather than zeroed covariates.
        """
        assert query.ctes is not None and "entity_metrics" in query.ctes
        entity_metrics_cte = query.ctes["entity_metrics"]
        assert isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery)
        entity_metrics_cte.expr.select.append(
            ast.Alias(
                alias="covariate_value",
                expr=self._build_funnel_covariate_value_expr(
                    events_alias=events_alias,
                    last_step_index=last_step_index,
                    exposure_alias=exposure_alias,
                ),
            )
        )
        query.select.extend(self._build_funnel_cuped_aggregation_aliases(last_step_index))

    def _extend_date_from_for_funnel_cuped(self, date_from: ast.Expr) -> ast.Expr:
        """
        Roll the funnel's `date_from` back by `lookback_days` when CUPED is
        enabled, so the same scan also feeds the CUPED pre-exposure window.
        Returns the input unchanged when CUPED is off.
        """
        if not self.cuped_config.enabled:
            return date_from
        return parse_expr(
            "{date_from} - toIntervalDay({lookback_days})",
            placeholders={
                "date_from": date_from,
                "lookback_days": ast.Constant(value=self.cuped_config.lookback_days),
            },
        )

    def _build_funnel_optimized_temporal_setup(self, is_unordered_funnel: bool) -> tuple[str, str, str]:
        """
        Returns (first_exposures_cte_str, temporal_join, having_clause) for the
        optimized funnel query.

        Three call sites collapse into one place:

        - Unordered funnels need temporal filtering because the UDF doesn't
          enforce that step_0 (exposure) precedes step_1..N. We exclude events
          before first exposure with an INNER JOIN + WHERE.
        - CUPED needs the per-entity exposure timestamp to scope the pre-window
          covariate, so we materialize first_exposures even when ordered. No
          WHERE filter is added: the aggregate_funnel_array UDF anchors on
          step_0 (date-bounded by the exposure predicate), so pre-window events
          with step_X=1 (X>0) are never used in the post-window result.
        - Otherwise, no first_exposures CTE; HAVING countIf(step_0 = 1) > 0
          is the cheapest way to keep only exposed entities.
        """
        return self._funnel_query_builder().build_funnel_optimized_temporal_setup(is_unordered_funnel)

    def _build_metric_predicate(
        self,
        source=None,
        table_alias: str = "events",
        cuped_lookback_days: int | None = None,
    ) -> ast.Expr:
        """
        Builds the metric predicate as an AST expression.
        For ratio metrics, pass the specific source (numerator or denominator) and table_alias.
        For mean metrics, uses self.metric.source by default with "events" alias.
        """
        if source is None:
            assert isinstance(self.metric, ExperimentMeanMetric)
            source = self.metric.source

        return build_metric_predicate(
            team=self.team,
            source=source,
            date_range_query=self.date_range_query,
            conversion_window_seconds=self._get_conversion_window_seconds(),
            table_alias=table_alias,
            cuped_lookback_days=cuped_lookback_days,
        )

    def _build_value_expr(self, source=None, apply_coalesce: bool = True) -> ast.Expr:
        """
        Extracts the value expression from the metric source configuration.
        For ratio metrics, pass the specific source (numerator or denominator).
        For mean metrics, uses self.metric.source by default.

        Args:
            source: The metric source configuration
            apply_coalesce: If True, wrap numeric values with coalesce(..., 0) so that
                           NULL property values are treated as 0. This should be True
                           for event CTEs (metric_events, numerator_events, denominator_events)
                           so that downstream aggregations don't need to distinguish between
                           metric types.

        Note: For count distinct math types (UNIQUE_SESSION, DAU, UNIQUE_GROUP), coalesce
        is not applied since the value is an ID, not a numeric value.
        """
        if source is None:
            assert isinstance(self.metric, ExperimentMeanMetric)
            source = self.metric.source

        return build_value_expr(source, apply_coalesce=apply_coalesce)

    def _build_value_aggregation_expr(
        self,
        source=None,
        events_alias: str = "metric_events",
        column_name: str = "value",
        value_expr: ast.Expr | None = None,
    ) -> ast.Expr:
        """
        Returns the value aggregation expression based on math type.
        For ratio metrics, pass the specific source (numerator or denominator) and events_alias.
        For mean metrics, uses self.metric.source by default with "metric_events" alias.

        Args:
            source: The metric source configuration
            events_alias: The table/CTE alias to use (e.g., "metric_events", "combined_events")
            column_name: The column name containing the value (e.g., "value", "numerator_value")

        Note: NULL handling (coalesce) is applied upstream in _build_value_expr() when building
        the event CTEs. This method does not need to handle NULLs - aggregation functions will
        naturally ignore NULLs from combined_events (ratio metrics), while NULL property values
        have already been coalesced to 0 at the source.
        """
        if source is None:
            assert isinstance(self.metric, ExperimentMeanMetric)
            source = self.metric.source

        return build_value_aggregation_expr(
            source,
            events_alias=events_alias,
            column_name=column_name,
            value_expr=value_expr,
        )

    def _build_test_accounts_filter(self) -> ast.Expr:
        return self._exposure_query_builder().build_test_accounts_filter()

    def _build_variant_property(self) -> ast.Field:
        """Derive which event property that should be used for variants"""
        return self._exposure_query_builder().build_variant_property()

    def _build_variant_expr_for_funnel(self) -> ast.Expr:
        """
        Builds the variant selection expression based on multiple variant handling.
        """
        return self._funnel_query_builder().build_variant_expr_for_funnel()

    def _build_exposure_event_predicate(self) -> ast.Expr:
        """
        Builds the event predicate for exposure filtering (without timestamp conditions).

        This handles:
        - Custom exposure events via event_or_action_to_filter
        - Special $feature_flag_called filtering (matching the flag key)

        Used by both _build_exposure_predicate() and get_exposure_query_for_precomputation().
        """
        return self._exposure_query_builder().build_exposure_event_predicate()

    def _build_exposure_predicate(self) -> ast.Expr:
        """
        Builds the exposure predicate as an AST expression.
        """
        return self._exposure_query_builder().build_exposure_predicate()

    def _get_exposure_query(self) -> ast.SelectQuery:
        return self._exposure_query_builder().select_query()

    def _build_exposure_select_query(self) -> ast.SelectQuery:
        return self._exposure_query_builder()._build_exposure_select_query()

    def _build_exposure_from_precomputed(self, job_ids: list[str]) -> ast.SelectQuery:
        """
        Builds the exposure CTE by reading from the lazy-computed table instead of scanning events.

        Re-aggregates across jobs since the same user can appear in multiple time-window jobs.
        Returns the same column shape as _build_exposure_select_query().

        Important: Jobs can cover broader time ranges than the experiment (for reusability),
        so we must filter by experiment start/end dates to avoid including exposures outside
        the experiment window.
        """
        return self._exposure_query_builder().precomputed_select_query(job_ids)

    def get_exposure_query_for_precomputation(self) -> tuple[str, dict[str, ast.Expr]]:
        """
        Returns the exposure query and placeholders for lazy computation.

        The query string uses {time_window_min} and {time_window_max} placeholders
        which are filled in by the lazy computation system for each daily bucket.
        Other placeholders are returned in the dict and should be passed to
        ensure_precomputed().

        Returns:
            Tuple of (query_string, placeholders_dict)
        """
        return self._exposure_query_builder().precomputation_query()

    def get_funnel_metric_events_query_for_precomputation(self) -> tuple[str, dict[str, ast.Expr]]:
        """
        Returns the SELECT query that the lazy computation system wraps in an
        INSERT INTO experiment_metric_events_preaggregated. This is the write
        path — it scans the events table and stores one row per matching event
        with step indicators packed into an Array(UInt8).

        The query uses {time_window_min} and {time_window_max} placeholders filled
        by the lazy computation system for each daily bucket.

        Returns:
            Tuple of (query_string, placeholders_dict)
        """
        return self._funnel_query_builder().get_funnel_metric_events_query_for_precomputation()

    def _build_variant_expr_for_mean(self) -> ast.Expr:
        """
        Builds the variant selection expression for mean metrics based on multiple variant handling.
        """
        return self._exposure_query_builder().build_variant_expr_for_mean()

    def _build_funnel_step_columns(self) -> list[ast.Alias]:
        """
        Builds list of step column AST expressions: step_0, step_1, etc.
        """
        return self._funnel_query_builder().build_funnel_step_columns()

    def _build_funnel_steps_filter(self) -> ast.Expr:
        """
        Returns the expression to filter funnel steps (matches ANY step) within
        the time period of the experiment + the conversion window if set.

        When CUPED is enabled, the lower bound is rolled back by `lookback_days`
        so the same scan also feeds the CUPED pre-exposure window.
        """
        return self._funnel_query_builder().build_funnel_steps_filter()

    def _build_funnel_aggregation_expr(self) -> ast.Expr:
        """
        Returns the funnel evaluation expression using aggregate_funnel_array.
        """
        return self._funnel_query_builder().build_funnel_aggregation_expr()

    def _build_uuid_to_session_map(self) -> ast.Expr:
        """
        Creates a map from event UUID to session ID for funnel metrics.
        """
        return self._funnel_query_builder().build_uuid_to_session_map()

    def _build_uuid_to_timestamp_map(self) -> ast.Expr:
        """
        Creates a map from event UUID to timestamp for funnel metrics.
        """
        return self._funnel_query_builder().build_uuid_to_timestamp_map()

    def _has_datawarehouse_steps(self) -> bool:
        """
        Check if funnel metric has any datawarehouse steps.

        Returns:
            True if any step in the series is ExperimentDataWarehouseNode
        """
        return self._funnel_query_builder().has_datawarehouse_steps()

    def _build_funnel_metric_events_union_query(self) -> ast.SelectSetQuery:
        """
        Build metric_events UNION ALL query for funnels with DW steps.

        Uses MetricSourceInfo and FunnelStepBuilder abstractions.

        Returns:
            SelectSetQuery with UNION ALL combining events and DW sources
        """
        return self._funnel_query_builder().build_funnel_metric_events_union_query()

    def _build_funnel_events_subquery_for_union(
        self, step_builder: FunnelStepBuilder, events_join_key: str
    ) -> ast.SelectQuery:
        """
        Build events subquery for UNION pattern.

        This subquery includes:
        - Exposure events (step_0=1 when exposure, 0 otherwise)
        - Event and action steps (step_N=1 when matches, 0 otherwise)
        - DW steps (always step_N=0 in this subquery)

        Args:
            step_builder: FunnelStepBuilder instance for step columns
            events_join_key: The event property key used to join with DW tables
                (e.g. "properties.$user_id"). Used as entity_id so it matches the
                DW subquery's data_warehouse_join_key.

        Returns:
            SELECT query for events table
        """
        return self._funnel_query_builder().build_funnel_events_subquery_for_union(step_builder, events_join_key)

    def _build_funnel_dw_step_subquery(
        self,
        step: ExperimentDataWarehouseNode,
        step_index: int,
        step_builder: FunnelStepBuilder,
    ) -> ast.SelectQuery:
        """
        Build subquery for a single DW step.

        Uses MetricSourceInfo and FunnelStepBuilder abstractions for normalized output.

        Args:
            step: The DW node configuration
            step_index: The step number (1-indexed, after exposure step_0)
            step_builder: FunnelStepBuilder instance for step columns

        Returns:
            SELECT query for DW table
        """
        return self._funnel_query_builder().build_funnel_dw_step_subquery(step, step_index, step_builder)

    def _build_dw_step_predicate(
        self,
        step: ExperimentDataWarehouseNode,
        source_info: MetricSourceInfo,
    ) -> ast.Expr:
        """
        Build WHERE predicate for DW step filtering.

        Filters by:
        - Timestamp range (experiment dates + conversion window)
        - DW node properties (custom filters)

        Args:
            step: The DW node configuration
            source_info: MetricSourceInfo for this DW source

        Returns:
            Filter expression
        """
        return self._funnel_query_builder().build_dw_step_predicate(step, source_info)

    # --- Optimized funnel query helpers ---

    def _build_variant_expr_for_funnel_optimized(self) -> ast.Expr:
        """
        Variant expression for the optimized funnel path.
        References variant_value (raw property) instead of variant (column in legacy metric_events).
        """
        return self._funnel_query_builder().build_variant_expr_for_funnel_optimized()

    def _build_funnel_aggregation_expr_optimized(self) -> ast.Expr:
        """
        Funnel aggregation for the optimized path. References base_events instead of metric_events.
        """
        return self._funnel_query_builder().build_funnel_aggregation_expr_optimized()

    def _build_uuid_to_session_map_optimized(self) -> ast.Expr:
        """
        UUID-to-session map for the optimized path. References base_events columns.
        """
        return self._funnel_query_builder().build_uuid_to_session_map_optimized()

    def _build_uuid_to_timestamp_map_optimized(self) -> ast.Expr:
        """
        UUID-to-timestamp map for the optimized path. References base_events columns.
        """
        return self._funnel_query_builder().build_uuid_to_timestamp_map_optimized()

    def _build_maturity_having_clause_optimized(self) -> Optional[ast.Expr]:
        """
        Maturity HAVING clause for the optimized path.
        Uses maxIf to only consider exposure events (step_0 = 1) for maturity,
        since entity_metrics groups over all events, not just exposures.
        """
        return self._funnel_query_builder().build_maturity_having_clause_optimized()

    def _build_retention_query(self) -> ast.SelectQuery:
        """
        Builds query for retention metrics.

        Retention measures the proportion of users who performed a "completion event"
        within a specified time window after performing a "start event".

        Statistical Treatment:
        This metric is treated as a ratio metric using RatioStatistic. Each entity has:
        - Numerator value: 1 if completed within retention window, 0 otherwise
        - Denominator value: 1 (they performed the start event)

        Unlike standard proportion tests (where sample size is fixed), retention metrics
        have a random denominator (count of users who started). This makes retention a
        ratio of two random variables, requiring delta method variance.

        Returns 7 fields for RatioStatistic:
        - Standard: num_users, total_sum, total_sum_of_squares
        - Ratio-specific: denominator_sum, denominator_sum_squares, numerator_denominator_sum_product

        The collected statistics are processed using RatioStatistic (not ProportionStatistic)
        for both frequentist and Bayesian analysis.

        Structure:
        - exposures: all exposures with variant assignment
        - start_events: when each entity performed the start_event (with start_handling logic)
        - completion_events: when each entity performed the completion_event
        - entity_metrics: join exposures + start_events + completion_events
                          Calculate retention per entity (1 if retained, 0 if not)
        - Final SELECT: aggregated statistics per variant

        Key Design Decision:
        Uses INNER JOIN between exposures and start_events, meaning only users who
        performed the start event are included in the retention calculation. This
        measures "Of users who did X, how many came back to do Y?" rather than
        "Of all exposed users, how many did X and then Y?"
        """
        return self._retention_query_builder().build_retention_query()

    def _build_start_event_timestamp_expr(self) -> ast.Expr:
        """
        Returns expression to get start event timestamp based on start_handling.
        FIRST_SEEN: Use the first occurrence of start event
        LAST_SEEN: Use the last occurrence of start event
        """
        return self._retention_query_builder().build_start_event_timestamp_expr()

    def _get_retention_window_truncation_expr(self, timestamp_expr: ast.Expr) -> ast.Expr:
        """
        Returns truncated timestamp expression for retention window comparisons.

        For DAY: returns toStartOfDay(timestamp)
        For HOUR: returns toStartOfHour(timestamp)
        For other units: returns timestamp unchanged

        This ensures [7,7] day window means "any time on day 7" rather than
        "exactly 7*24 hours after start event to the second".
        """
        return self._retention_query_builder().get_retention_window_truncation_expr(timestamp_expr)

    def _build_retention_window_interval(self, window_value: int) -> ast.Expr:
        """
        Converts retention window value to ClickHouse interval expression.
        """
        return self._retention_query_builder().build_retention_window_interval(window_value)

    def _build_start_event_predicate(self) -> ast.Expr:
        """
        Builds the predicate for filtering start events.
        """
        return self._retention_query_builder().build_start_event_predicate()

    def _build_completion_event_predicate(self) -> ast.Expr:
        """
        Builds the predicate for filtering completion events.
        """
        return self._retention_query_builder().build_completion_event_predicate()

    def _build_start_after_exposure_predicate(self) -> ast.Expr:
        """
        Builds the predicate for filtering start events to only those after exposure.
        Applied inside the start_events CTE (pre-aggregation) so that min/max only
        considers events after the user's first exposure.
        """
        return self._retention_query_builder().build_start_after_exposure_predicate()

    def _build_completion_retention_window_predicate(self) -> ast.Expr:
        """
        Builds the predicate for the join condition ensuring completion events
        are within a reasonable timeframe relative to start events.

        This is a performance optimization - we'll do the exact retention window
        calculation in the entity_metrics CTE.

        For DAY/HOUR units that use timestamp truncation, we add a buffer to account
        for the truncation window. This ensures that same-period retention (e.g., [0,0])
        captures all events within that period, not just events at the exact same second.
        """
        return self._retention_query_builder().build_completion_retention_window_predicate()
