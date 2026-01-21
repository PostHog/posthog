from typing import Optional, Union, cast

from posthog.schema import (
    ActionsNode,
    Breakdown,
    ExperimentDataWarehouseNode,
    ExperimentEventExposureConfig,
    ExperimentExposureCriteria,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    FunnelConversionWindowTimeUnit,
    MultipleVariantHandling,
    StartHandling,
    StepOrderValue,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.experiments.base_query_utils import (
    conversion_window_to_seconds,
    data_warehouse_node_to_filter,
    event_or_action_to_filter,
    funnel_evaluation_expr,
    funnel_steps_to_filter,
    get_source_value_expr,
)
from posthog.hogql_queries.experiments.exposure_query_logic import normalize_to_exposure_criteria
from posthog.hogql_queries.experiments.hogql_aggregation_utils import (
    build_aggregation_call,
    extract_aggregation_and_inner_expr,
)
from posthog.hogql_queries.insights.utils.utils import get_start_of_interval_hogql
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team

# Constant for representing NULL breakdown values
BREAKDOWN_NULL_STRING_LABEL = "$$_posthog_breakdown_null_$$"


def get_exposure_config_params_for_builder(
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None],
) -> tuple[ExperimentEventExposureConfig | ActionsNode, MultipleVariantHandling, bool]:
    """Returns exposure-related parameters required by the query builder."""
    criteria = normalize_to_exposure_criteria(exposure_criteria)
    exposure_config: ExperimentEventExposureConfig | ActionsNode
    if criteria is None:
        exposure_config = ExperimentEventExposureConfig(event="$feature_flag_called", properties=[])
        filter_test_accounts = False
        multiple_variant_handling = MultipleVariantHandling.EXCLUDE
    else:
        if criteria.exposure_config is None:
            exposure_config = ExperimentEventExposureConfig(event="$feature_flag_called", properties=[])
        else:
            exposure_config = criteria.exposure_config
        filter_test_accounts = bool(criteria.filterTestAccounts) if criteria.filterTestAccounts is not None else False
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
    ):
        self.team = team
        self.metric = metric
        self.feature_flag_key = feature_flag_key
        self.variants = variants
        self.date_range_query = date_range_query
        self.entity_key = entity_key
        self.exposure_config = exposure_config
        self.filter_test_accounts = filter_test_accounts
        self.multiple_variant_handling = multiple_variant_handling
        self.breakdowns = breakdowns or []

    def _has_breakdown(self) -> bool:
        """Returns True if breakdown is configured"""
        return len(self.breakdowns) > 0

    def _get_breakdown_count(self) -> int:
        """Returns the number of breakdowns configured"""
        return len(self.breakdowns)

    def _get_breakdown_aliases(self) -> list[str]:
        """Returns list of breakdown aliases: ['breakdown_value_1', 'breakdown_value_2', ...]"""
        return [f"breakdown_value_{i + 1}" for i in range(len(self.breakdowns))]

    def _build_breakdown_exprs(self, table_alias: str = "events") -> list[tuple[str, ast.Expr]]:
        """
        Returns list of (alias, expression) tuples for extracting breakdown properties from events.
        Handles NULL values by replacing with BREAKDOWN_NULL_STRING_LABEL.
        Returns empty list if no breakdowns configured.
        """
        if not self._has_breakdown():
            return []

        result = []
        for i, breakdown in enumerate(self.breakdowns):
            # Build the property chain - if table_alias is empty, just use properties.breakdown
            if table_alias:
                property_expr = ast.Field(chain=[table_alias, "properties", breakdown.property])
            else:
                property_expr = ast.Field(chain=["properties", breakdown.property])

            expr = parse_expr(
                "coalesce(toString({property_expr}), {null_label})",
                placeholders={
                    "property_expr": property_expr,
                    "null_label": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                },
            )
            alias = f"breakdown_value_{i + 1}"
            result.append((alias, expr))

        return result

    def build_query(self) -> ast.SelectQuery:
        """
        Main entry point. Returns complete query built from HogQL with placeholders.
        """
        assert self.metric is not None, "metric is required for build_query()"
        match self.metric:
            case ExperimentFunnelMetric():
                return self._build_funnel_query()
            case ExperimentMeanMetric():
                return self._build_mean_query()
            case ExperimentRatioMetric():
                return self._build_ratio_query()
            case ExperimentRetentionMetric():
                return self._build_retention_query()
            case _:
                raise NotImplementedError(
                    f"Only funnel, mean, ratio, and retention metrics are supported. Got {type(self.metric)}"
                )

    def get_exposure_timeseries_query(self) -> ast.SelectQuery:
        """
        Returns a query for exposure timeseries data.

        Generates daily exposure counts per variant, counting each entity
        only once on their first exposure day.

        Returns:
            SelectQuery with columns: day, variant, exposed_count
        """
        query = parse_select(
            """
            WITH first_exposures AS (
                SELECT
                    {entity_key} AS entity_id,
                    {variant_expr} AS variant,
                    toDate(toString(min(timestamp))) AS day
                FROM events
                WHERE {exposure_predicate}
                GROUP BY entity_id
            )

            SELECT
                first_exposures.day AS day,
                first_exposures.variant AS variant,
                count(first_exposures.entity_id) AS exposed_count
            FROM first_exposures
            WHERE notEmpty(variant)
            GROUP BY first_exposures.day, first_exposures.variant
            ORDER BY first_exposures.day ASC
            """,
            placeholders={
                "entity_key": parse_expr(self.entity_key),
                "variant_expr": self._build_variant_expr_for_mean(),
                "exposure_predicate": self._build_exposure_predicate(),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    def _get_conversion_window_seconds(self) -> int:
        """
        Returns the conversion window in seconds for the current metric.
        Returns 0 if no conversion window is configured.
        """
        assert self.metric is not None, "metric is required for _get_conversion_window_seconds()"
        if self.metric.conversion_window and self.metric.conversion_window_unit:
            return conversion_window_to_seconds(
                self.metric.conversion_window,
                self.metric.conversion_window_unit,
            )
        return 0

    def _inject_funnel_breakdown_columns(self, query: ast.SelectQuery) -> None:
        """
        Injects breakdown columns into funnel query AST.
        Modifies query in-place.
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()
        breakdown_exprs = self._build_breakdown_exprs(table_alias="")

        # Inject into metric_events CTE SELECT
        if query.ctes and "metric_events" in query.ctes:
            metric_events_cte = query.ctes["metric_events"]
            if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    metric_events_cte.expr.select.append(ast.Alias(alias=alias, expr=expr))

        # Inject into entity_metrics CTE SELECT (attribution - extract from exposure events only)
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        parse_expr(f"argMinIf({alias}, timestamp, step_0 = 1) AS {alias}")
                    )

        # Inject into final SELECT - breakdown columns must come right after variant
        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias])),
            )

        # Inject into final GROUP BY
        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=["entity_metrics", alias]))

    def _build_funnel_query(self) -> ast.SelectQuery:
        """
        Builds query for funnel metrics.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)

        num_steps = len(self.metric.series) + 1  #  +1 as we are including exposure criteria

        metric_events_cte_str = """
                metric_events AS (
                    SELECT
                        {entity_key} AS entity_id,
                        {variant_property} as variant,
                        timestamp,
                        uuid,
                        properties.$session_id AS session_id,
                        -- step_0, step_1, ... step_N columns added programmatically below
                    FROM events
                    WHERE ({exposure_predicate} OR {funnel_steps_filter})
                )
        """

        is_unordered_funnel = self.metric.funnel_order_type == StepOrderValue.UNORDERED

        # For unordered funnels, the UDF does _not_ filter out funnel steps that occur _before_ the
        # exposure event. Thus, we need to filter them out with a left join. An attempt to do this with
        # a window function has been tried, but it failed with a "column not found" issue due to how
        # HogQL rewrites the query and hitting a bug with the ClickHouse analyzer
        if is_unordered_funnel:
            ctes_sql = f"""
                exposures AS (
                    {{exposure_select_query}}
                ),

                {metric_events_cte_str},

                entity_metrics AS (
                    SELECT
                        exposures.entity_id AS entity_id,
                        exposures.variant AS variant,
                        exposures.exposure_event_uuid AS exposure_event_uuid,
                        exposures.exposure_session_id AS exposure_session_id,
                        exposures.first_exposure_time AS exposure_timestamp,
                        {{funnel_aggregation}} AS value,
                        {{uuid_to_session_map}} AS uuid_to_session,
                        {{uuid_to_timestamp_map}} AS uuid_to_timestamp
                    FROM exposures
                    LEFT JOIN metric_events
                        ON exposures.entity_id = metric_events.entity_id
                        AND metric_events.timestamp >= exposures.first_exposure_time
                    GROUP BY
                        exposures.entity_id,
                        exposures.variant,
                        exposures.exposure_event_uuid,
                        exposures.exposure_session_id,
                        exposures.first_exposure_time
                )
            """
        else:
            ctes_sql = f"""
                {metric_events_cte_str},

                entity_metrics AS (
                    SELECT
                        entity_id,
                        {{variant_expr}} as variant,
                        argMinIf(uuid, timestamp, step_0 = 1) AS exposure_event_uuid,
                        argMinIf(session_id, timestamp, step_0 = 1) AS exposure_session_id,
                        argMinIf(timestamp, timestamp, step_0 = 1) AS exposure_timestamp,
                        {{funnel_aggregation}} AS value,
                        {{uuid_to_session_map}} AS uuid_to_session,
                        {{uuid_to_timestamp_map}} AS uuid_to_timestamp
                    FROM metric_events
                    GROUP BY entity_id
                )
            """

        placeholders: dict[str, ast.Expr | ast.SelectQuery] = {
            "exposure_predicate": self._build_exposure_predicate(),
            "variant_property": self._build_variant_property(),
            "variant_expr": self._build_variant_expr_for_funnel(),
            "entity_key": parse_expr(self.entity_key),
            "funnel_steps_filter": self._build_funnel_steps_filter(),
            "funnel_aggregation": self._build_funnel_aggregation_expr(),
            "num_steps_minus_1": ast.Constant(value=num_steps - 1),
            "uuid_to_session_map": self._build_uuid_to_session_map(),
            "uuid_to_timestamp_map": self._build_uuid_to_timestamp_map(),
        }

        if is_unordered_funnel:
            placeholders["exposure_select_query"] = self._build_exposure_select_query()

        query = parse_select(
            f"""
            WITH
            {ctes_sql}

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                -- The return value from the funnel eval is zero indexed. So reaching first step means
                -- it return 0, and so on. So reaching the last step means it will return
                -- num_steps - 1
                countIf(entity_metrics.value.1 = {{num_steps_minus_1}}) AS total_sum,
                countIf(entity_metrics.value.1 = {{num_steps_minus_1}}) AS total_sum_of_squares
                -- step_counts added programmatically below
                -- steps_event_data added programmatically below
                -- breakdown columns added programmatically below
            FROM entity_metrics
            WHERE notEmpty(variant)
            GROUP BY entity_metrics.variant
            -- breakdown columns added programmatically below
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns into the query AST
        self._inject_funnel_breakdown_columns(query)

        # Inject step columns into the metric_events CTE
        # Find the metric_events CTE in the query
        if query.ctes and "metric_events" in query.ctes:
            metric_events_cte = query.ctes["metric_events"]
            if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
                # Add step columns to the SELECT
                step_columns = self._build_funnel_step_columns()
                metric_events_cte.expr.select.extend(step_columns)

        # Inject the additional selects we do for getting the data we need to render the funnel chart
        # Add step counts - how many users reached each step
        step_count_exprs = []
        for i in range(1, num_steps):
            step_count_exprs.append(f"countIf(entity_metrics.value.1 >= {i})")
        step_counts_expr = f"tuple({', '.join(step_count_exprs)}) as step_counts"

        # For each step in the funnel, get at least 100 tuples of person_id, session_id, event uuid, and timestamp, that have
        # that step as their last step in the funnel.
        # For the users that have 0 matching steps in the funnel (-1), we return the event data for the exposure event.
        event_uuids_exprs = []
        for i in range(1, num_steps + 1):
            event_uuids_expr = f"""
                groupArraySampleIf(100)(
                    if(
                        entity_metrics.value.2 != '',
                        tuple(toString(entity_metrics.entity_id), uuid_to_session[entity_metrics.value.2], entity_metrics.value.2, toString(uuid_to_timestamp[entity_metrics.value.2])),
                        tuple(toString(entity_metrics.entity_id), toString(entity_metrics.exposure_session_id), toString(entity_metrics.exposure_event_uuid), toString(entity_metrics.exposure_timestamp))
                    ),
                    entity_metrics.value.1 = {i} - 1
                )
            """
            event_uuids_exprs.append(event_uuids_expr)
        event_uuids_exprs_sql = f"tuple({', '.join(event_uuids_exprs)}) as steps_event_data"

        query.select.extend([parse_expr(step_counts_expr), parse_expr(event_uuids_exprs_sql)])

        return query

    def _get_mean_query_common_ctes(self) -> str:
        """
        Returns the common CTEs used by both regular and winsorized mean queries.
        Supports both regular events and data warehouse sources.
        """
        assert isinstance(self.metric, ExperimentMeanMetric)
        is_dw = isinstance(self.metric.source, ExperimentDataWarehouseNode)

        if is_dw:
            assert isinstance(self.metric.source, ExperimentDataWarehouseNode)
            table = self.metric.source.table_name
            timestamp_field = self.metric.source.timestamp_field
            join_condition = "{join_condition}"
        else:
            table = "events"
            timestamp_field = "timestamp"
            join_condition = "exposures.entity_id = metric_events.entity_id"

        return f"""
            exposures AS (
                {{exposure_select_query}}
            ),

            metric_events AS (
                SELECT
                    {{entity_key}} AS entity_id,
                    {timestamp_field} AS timestamp,
                    {{value_expr}} AS value
                    -- breakdown columns added programmatically below
                FROM {table}
                WHERE {{metric_predicate}}
            ),

            entity_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    {{value_agg}} AS value
                    -- breakdown columns added programmatically below
                FROM exposures
                LEFT JOIN metric_events ON {join_condition}
                    AND {{conversion_window_predicate}}
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
        is_dw = isinstance(self.metric.source, ExperimentDataWarehouseNode)

        # Build exposure query with exposure_identifier for data warehouse
        exposure_query = self._build_exposure_select_query()
        if is_dw:
            assert isinstance(self.metric.source, ExperimentDataWarehouseNode)
            events_join_key_parts = cast(list[str | int], self.metric.source.events_join_key.split("."))
            exposure_query.select.append(
                ast.Alias(
                    alias="exposure_identifier",
                    expr=ast.Field(chain=events_join_key_parts),
                )
            )
            if exposure_query.group_by:
                exposure_query.group_by.append(ast.Field(chain=events_join_key_parts))

        if is_dw:
            assert isinstance(self.metric.source, ExperimentDataWarehouseNode)
            table = self.metric.source.table_name
            entity_field = self.metric.source.data_warehouse_join_key
        else:
            table = "events"
            entity_field = self.entity_key

        placeholders: dict = {
            "exposure_select_query": exposure_query,
            "entity_key": parse_expr(entity_field),
            "metric_predicate": self._build_metric_predicate(table_alias=table),
            "value_expr": self._build_value_expr(),
            "value_agg": self._build_value_aggregation_expr(),
            "conversion_window_predicate": self._build_conversion_window_predicate(),
        }

        # Add join condition for data warehouse
        if is_dw:
            placeholders["join_condition"] = parse_expr(
                "toString(exposures.exposure_identifier) = toString(metric_events.entity_id)"
            )

        return placeholders

    def _inject_mean_breakdown_columns(self, query: ast.SelectQuery, final_cte_name: str = "entity_metrics") -> None:
        """
        Injects breakdown columns into mean query AST.
        Modifies query in-place.

        Args:
            query: The parsed SelectQuery AST
            final_cte_name: Name of the final CTE before main SELECT ('entity_metrics' or 'winsorized_entity_metrics')
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()

        # Get table name for metric_events based on metric source
        assert isinstance(self.metric, ExperimentMeanMetric)
        is_dw = isinstance(self.metric.source, ExperimentDataWarehouseNode)

        breakdown_exprs = self._build_breakdown_exprs(table_alias="metric_events" if is_dw else "events")

        # Inject into metric_events CTE SELECT
        if query.ctes and "metric_events" in query.ctes:
            metric_events_cte = query.ctes["metric_events"]
            if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    metric_events_cte.expr.select.append(ast.Alias(alias=alias, expr=expr))

        # Inject into entity_metrics CTE SELECT and GROUP BY
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["exposures", alias]))
                    )
                # Also add to GROUP BY
                if entity_metrics_cte.expr.group_by is None:
                    entity_metrics_cte.expr.group_by = []
                for alias in aliases:
                    entity_metrics_cte.expr.group_by.append(ast.Field(chain=["exposures", alias]))

        # Inject into percentiles CTE (only for winsorization queries)
        if query.ctes and "percentiles" in query.ctes:
            percentiles_cte = query.ctes["percentiles"]
            if isinstance(percentiles_cte, ast.CTE) and isinstance(percentiles_cte.expr, ast.SelectQuery):
                # Add breakdown columns to SELECT
                for alias in aliases:
                    percentiles_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias]))
                    )
                # Initialize and populate GROUP BY for per-breakdown percentiles
                if percentiles_cte.expr.group_by is None:
                    percentiles_cte.expr.group_by = []
                for alias in aliases:
                    percentiles_cte.expr.group_by.append(ast.Field(chain=["entity_metrics", alias]))

        # Inject into winsorized_entity_metrics CTE (only when final_cte_name is winsorized_entity_metrics)
        if query.ctes and final_cte_name == "winsorized_entity_metrics":
            winsorized_cte = query.ctes["winsorized_entity_metrics"]
            if isinstance(winsorized_cte, ast.CTE) and isinstance(winsorized_cte.expr, ast.SelectQuery):
                # Add breakdown columns to SELECT
                for alias in aliases:
                    winsorized_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias]))
                    )
                # Convert CROSS JOIN to proper JOIN with breakdown conditions
                if winsorized_cte.expr.select_from:
                    join_expr = winsorized_cte.expr.select_from.next_join
                    if join_expr and isinstance(join_expr, ast.JoinExpr):
                        # Change from CROSS JOIN to INNER JOIN
                        join_expr.join_type = "JOIN"
                        # Build join condition: percentiles.bd1 = entity_metrics.bd1 AND ...
                        join_conditions = []
                        for alias in aliases:
                            join_conditions.append(
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["percentiles", alias]),
                                    right=ast.Field(chain=["entity_metrics", alias]),
                                )
                            )
                        # Combine conditions with AND
                        condition_expr: ast.Expr
                        if len(join_conditions) == 1:
                            condition_expr = join_conditions[0]
                        else:
                            combined: ast.Expr = join_conditions[0]
                            for condition in join_conditions[1:]:
                                combined = ast.And(exprs=[combined, condition])
                            condition_expr = combined
                        # Wrap in JoinConstraint with ON clause
                        join_expr.constraint = ast.JoinConstraint(expr=condition_expr, constraint_type="ON")

        # Inject into final SELECT - breakdown columns must come right after variant
        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=[final_cte_name, alias])),
            )

        # Inject into final GROUP BY
        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=[final_cte_name, alias]))

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

        query = parse_select(
            f"""
            WITH {common_ctes}

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                sum(entity_metrics.value) AS total_sum,
                sum(power(entity_metrics.value, 2)) AS total_sum_of_squares
                -- breakdown columns added programmatically below
            FROM entity_metrics
            GROUP BY entity_metrics.variant
            -- breakdown columns added programmatically below
            """,
            placeholders=self._get_mean_query_common_placeholders(),
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns into the query AST
        self._inject_mean_breakdown_columns(query, final_cte_name="entity_metrics")

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
                "quantile({level})(entity_metrics.value)",
                placeholders={"level": ast.Constant(value=self.metric.lower_bound_percentile)},
            )
        else:
            lower_bound_expr = parse_expr("min(entity_metrics.value)")

        # Build upper bound expression
        if self.metric.upper_bound_percentile is not None:
            # Handle ignore_zeros flag for upper bound calculation
            if getattr(self.metric, "ignore_zeros", False):
                upper_bound_expr = parse_expr(
                    "quantile({level})(if(entity_metrics.value != 0, entity_metrics.value, null))",
                    placeholders={"level": ast.Constant(value=self.metric.upper_bound_percentile)},
                )
            else:
                upper_bound_expr = parse_expr(
                    "quantile({level})(entity_metrics.value)",
                    placeholders={"level": ast.Constant(value=self.metric.upper_bound_percentile)},
                )
        else:
            upper_bound_expr = parse_expr("max(entity_metrics.value)")

        common_ctes = self._get_mean_query_common_ctes()
        placeholders = self._get_mean_query_common_placeholders()

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
                    least(greatest(percentiles.lower_bound, entity_metrics.value), percentiles.upper_bound) AS value
                    -- breakdown columns added programmatically below
                FROM entity_metrics
                CROSS JOIN percentiles
                -- JOIN conditions added programmatically below if breakdowns exist
            )

            SELECT
                winsorized_entity_metrics.variant AS variant,
                count(winsorized_entity_metrics.entity_id) AS num_users,
                sum(winsorized_entity_metrics.value) AS total_sum,
                sum(power(winsorized_entity_metrics.value, 2)) AS total_sum_of_squares
                -- breakdown columns added programmatically below
            FROM winsorized_entity_metrics
            GROUP BY winsorized_entity_metrics.variant
            -- breakdown columns added programmatically below
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns into the query AST
        self._inject_mean_breakdown_columns(query, final_cte_name="winsorized_entity_metrics")

        return query

    def _inject_ratio_breakdown_columns(self, query: ast.SelectQuery) -> None:
        """
        Injects breakdown columns into ratio query AST.
        Modifies query in-place.

        With the combined_events structure, breakdowns are simpler:
        - Breakdowns are attributed from exposures (not from numerator/denominator events)
        - entity_metrics gets breakdown columns directly from exposures
        - No need for breakdown join conditions since there's only one join to combined_events
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()

        # Inject into entity_metrics CTE SELECT and GROUP BY (from exposures)
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["exposures", alias]))
                    )
                if entity_metrics_cte.expr.group_by is None:
                    entity_metrics_cte.expr.group_by = []
                for alias in aliases:
                    entity_metrics_cte.expr.group_by.append(ast.Field(chain=["exposures", alias]))

        # Inject into final SELECT - breakdown columns must come right after variant
        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias])),
            )

        # Inject into final GROUP BY
        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=["entity_metrics", alias]))

    def _inject_retention_breakdown_columns(self, query: ast.SelectQuery) -> None:
        """
        Injects breakdown columns into retention query AST.
        Modifies query in-place.

        Retention breakdown injection is simpler than ratio because:
        - Only entity_metrics CTE needs modification
        - No JOIN conditions require breakdown columns
        - Breakdowns come from exposures only
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()

        # Inject into entity_metrics CTE SELECT and GROUP BY (carry breakdown from exposures)
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                # Add breakdown columns to SELECT (after entity_id and variant)
                for i, alias in enumerate(aliases):
                    entity_metrics_cte.expr.select.insert(
                        2 + i,  # After entity_id (0), variant (1)
                        ast.Alias(alias=alias, expr=ast.Field(chain=["exposures", alias])),
                    )

                # Add breakdown columns to GROUP BY
                if entity_metrics_cte.expr.group_by is None:
                    entity_metrics_cte.expr.group_by = []
                for alias in aliases:
                    entity_metrics_cte.expr.group_by.append(ast.Field(chain=["exposures", alias]))

        # Inject into final SELECT - breakdown columns must come right after variant
        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias])),
            )

        # Inject into final GROUP BY
        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=["entity_metrics", alias]))

    def _build_ratio_query(self) -> ast.SelectQuery:
        """
        Builds query for ratio metrics.

        Optimized structure using combined_events to reduce join operations:
        - exposures: all exposures with variant assignment (with exposure_identifier for data warehouse)
        - numerator_events: events for numerator metric with value
        - denominator_events: events for denominator metric with value
        - combined_events: UNION ALL of numerator and denominator events with NULL for non-applicable columns
        - entity_metrics: single join of exposures to combined_events, aggregating both metrics in one pass
        - Final SELECT: aggregated statistics per variant

        This approach reduces memory pressure by joining exposures to events only once
        instead of separately for numerator and denominator.
        """
        assert isinstance(self.metric, ExperimentRatioMetric)

        # Check if we're dealing with data warehouse sources
        num_is_dw = isinstance(self.metric.numerator, ExperimentDataWarehouseNode)
        denom_is_dw = isinstance(self.metric.denominator, ExperimentDataWarehouseNode)

        # Build numerator events CTE
        if num_is_dw:
            assert isinstance(self.metric.numerator, ExperimentDataWarehouseNode)
            num_table = self.metric.numerator.table_name
            num_entity_field = f"{self.metric.numerator.data_warehouse_join_key}"
            num_timestamp_field = self.metric.numerator.timestamp_field
        else:
            num_table = "events"
            num_entity_field = self.entity_key
            num_timestamp_field = f"{num_table}.timestamp"

        # Build denominator events CTE
        if denom_is_dw:
            assert isinstance(self.metric.denominator, ExperimentDataWarehouseNode)
            denom_table = self.metric.denominator.table_name
            denom_entity_field = f"{self.metric.denominator.data_warehouse_join_key}"
            denom_timestamp_field = self.metric.denominator.timestamp_field
        else:
            denom_table = "events"
            denom_entity_field = self.entity_key
            denom_timestamp_field = f"{denom_table}.timestamp"

        # Build exposure query with conditional exposure_identifier(s)
        exposure_query = self._build_exposure_select_query()
        if num_is_dw or denom_is_dw:
            # Add exposure_identifier fields for data warehouse joins
            # Support different join keys for numerator and denominator
            if num_is_dw:
                num_source = cast(ExperimentDataWarehouseNode, self.metric.numerator)
                num_join_key_parts = cast(list[str | int], num_source.events_join_key.split("."))
                exposure_query.select.append(
                    ast.Alias(
                        alias="exposure_identifier_num",
                        expr=ast.Field(chain=num_join_key_parts),
                    )
                )
                if exposure_query.group_by:
                    exposure_query.group_by.append(ast.Field(chain=num_join_key_parts))

            if denom_is_dw:
                denom_source = cast(ExperimentDataWarehouseNode, self.metric.denominator)
                denom_join_key_parts = cast(list[str | int], denom_source.events_join_key.split("."))
                exposure_query.select.append(
                    ast.Alias(
                        alias="exposure_identifier_denom",
                        expr=ast.Field(chain=denom_join_key_parts),
                    )
                )
                if exposure_query.group_by:
                    exposure_query.group_by.append(ast.Field(chain=denom_join_key_parts))

        # Build join condition for combined_events based on source_type
        # For DW sources, we need to handle different join keys for numerator and denominator
        if num_is_dw and denom_is_dw:
            # Both are DW with potentially different join keys
            join_cond = """(
                (combined_events.source_type = 'numerator' AND toString(exposures.exposure_identifier_num) = toString(combined_events.entity_id))
                OR
                (combined_events.source_type = 'denominator' AND toString(exposures.exposure_identifier_denom) = toString(combined_events.entity_id))
            )"""
        elif num_is_dw:
            join_cond = """(
                (combined_events.source_type = 'numerator' AND toString(exposures.exposure_identifier_num) = toString(combined_events.entity_id))
                OR
                (combined_events.source_type = 'denominator' AND exposures.entity_id = combined_events.entity_id)
            )"""
        elif denom_is_dw:
            join_cond = """(
                (combined_events.source_type = 'numerator' AND exposures.entity_id = combined_events.entity_id)
                OR
                (combined_events.source_type = 'denominator' AND toString(exposures.exposure_identifier_denom) = toString(combined_events.entity_id))
            )"""
        else:
            # Simple case: both use the same entity key, no need for source_type check
            join_cond = "exposures.entity_id = combined_events.entity_id"

        common_ctes = f"""
            exposures AS (
                {{exposure_select_query}}
            ),

            numerator_events AS (
                SELECT
                    {{num_entity_key}} AS entity_id,
                    {num_timestamp_field} AS timestamp,
                    {{numerator_value_expr}} AS value
                FROM {num_table}
                WHERE {{numerator_predicate}}
            ),

            denominator_events AS (
                SELECT
                    {{denom_entity_key}} AS entity_id,
                    {denom_timestamp_field} AS timestamp,
                    {{denominator_value_expr}} AS value
                FROM {denom_table}
                WHERE {{denominator_predicate}}
            ),

            combined_events AS (
                SELECT
                    entity_id,
                    timestamp,
                    value AS numerator_value,
                    NULL AS denominator_value,
                    'numerator' AS source_type
                FROM numerator_events
                UNION ALL
                SELECT
                    entity_id,
                    timestamp,
                    NULL AS numerator_value,
                    value AS denominator_value,
                    'denominator' AS source_type
                FROM denominator_events
            ),

            entity_metrics AS (
                SELECT
                    exposures.variant AS variant,
                    exposures.entity_id AS entity_id,
                    {{numerator_agg}} AS numerator_value,
                    {{denominator_agg}} AS denominator_value
                    -- breakdown columns added programmatically below
                FROM exposures
                LEFT JOIN combined_events
                    ON {join_cond}
                    AND {{conversion_window_predicate}}
                GROUP BY exposures.variant, exposures.entity_id
                -- breakdown columns added programmatically below
            )
        """

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
            placeholders={
                "exposure_select_query": exposure_query,
                "num_entity_key": parse_expr(num_entity_field),
                "denom_entity_key": parse_expr(denom_entity_field),
                "numerator_predicate": self._build_metric_predicate(
                    source=self.metric.numerator, table_alias=num_table
                ),
                "numerator_value_expr": self._build_value_expr(source=self.metric.numerator),
                "numerator_agg": self._build_value_aggregation_expr(
                    source=self.metric.numerator, events_alias="combined_events", column_name="numerator_value"
                ),
                "denominator_predicate": self._build_metric_predicate(
                    source=self.metric.denominator, table_alias=denom_table
                ),
                "denominator_value_expr": self._build_value_expr(source=self.metric.denominator),
                "denominator_agg": self._build_value_aggregation_expr(
                    source=self.metric.denominator, events_alias="combined_events", column_name="denominator_value"
                ),
                "conversion_window_predicate": self._build_conversion_window_predicate_for_events("combined_events"),
            },
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns into the query AST
        self._inject_ratio_breakdown_columns(query)

        return query

    def _build_conversion_window_predicate(self) -> ast.Expr:
        """
        Build the predicate for limiting metric events to the conversion window for the user.
        Uses "metric_events" as the events alias.
        """
        return self._build_conversion_window_predicate_for_events("metric_events")

    def _build_conversion_window_predicate_for_events(self, events_alias: str) -> ast.Expr:
        """
        Build the predicate for limiting metric events to the conversion window for the user.
        Parameterized to support different event table aliases (for ratio metrics).
        """
        conversion_window_seconds = self._get_conversion_window_seconds()
        if conversion_window_seconds > 0:
            return parse_expr(
                f"""
                {events_alias}.timestamp >= exposures.first_exposure_time
                AND {events_alias}.timestamp
                    < exposures.last_exposure_time + toIntervalSecond({{conversion_window_seconds}})
                """,
                placeholders={
                    "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                },
            )
        else:
            return parse_expr(f"{events_alias}.timestamp >= exposures.first_exposure_time")

    def _build_metric_predicate(self, source=None, table_alias: str = "events") -> ast.Expr:
        """
        Builds the metric predicate as an AST expression.
        For ratio metrics, pass the specific source (numerator or denominator) and table_alias.
        For mean metrics, uses self.metric.source by default with "events" alias.
        """
        if source is None:
            assert isinstance(self.metric, ExperimentMeanMetric)
            source = self.metric.source

        # Data warehouse sources use different table and predicate logic
        timestamp_field_chain: list[str | int]
        if isinstance(source, ExperimentDataWarehouseNode):
            # For DW tables, don't prefix with table name since:
            # 1. We're in a single-table CTE context where field names are unambiguous
            # 2. DW table names may contain dots (e.g., "bigquery.table_name") which
            #    confuse HogQL field resolution when used as a prefix
            timestamp_field_chain = [source.timestamp_field]
            metric_event_filter = data_warehouse_node_to_filter(self.team, source)
        else:
            timestamp_field_chain = [table_alias, "timestamp"]
            metric_event_filter = event_or_action_to_filter(self.team, source)

        conversion_window_seconds = self._get_conversion_window_seconds()

        return parse_expr(
            """
            {timestamp_field} >= {date_from}
            AND {timestamp_field} < {date_to} + toIntervalSecond({conversion_window_seconds})
            AND {metric_event_filter}
            """,
            placeholders={
                "timestamp_field": ast.Field(chain=timestamp_field_chain),
                "date_from": self.date_range_query.date_from_as_hogql(),
                "date_to": self.date_range_query.date_to_as_hogql(),
                "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                "metric_event_filter": metric_event_filter,
            },
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

        base_expr = get_source_value_expr(source)

        if not apply_coalesce:
            return base_expr

        # Check if this is a count distinct math type - don't coalesce IDs
        math_type = getattr(source, "math", ExperimentMetricMathType.TOTAL)
        if math_type in [
            ExperimentMetricMathType.UNIQUE_SESSION,
            ExperimentMetricMathType.DAU,
            ExperimentMetricMathType.UNIQUE_GROUP,
        ]:
            return base_expr

        # Wrap numeric values with coalesce so NULL property values become 0
        # We need toFloat to ensure type consistency - base_expr could be String (HOGQL),
        # Float64 (continuous), or UInt8 (count). Coalesce requires matching types.
        # Skip wrapping with toFloat if base_expr is already a toFloat call (e.g., continuous metrics)
        if isinstance(base_expr, ast.Call) and base_expr.name == "toFloat":
            float_expr = base_expr
        else:
            float_expr = ast.Call(name="toFloat", args=[base_expr])
        return ast.Call(name="coalesce", args=[float_expr, ast.Constant(value=0)])

    def _build_value_aggregation_expr(
        self, source=None, events_alias: str = "metric_events", column_name: str = "value"
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

        math_type = getattr(source, "math", ExperimentMetricMathType.TOTAL)
        column_ref = f"{events_alias}.{column_name}"

        if math_type in [
            ExperimentMetricMathType.UNIQUE_SESSION,
            ExperimentMetricMathType.DAU,
            ExperimentMetricMathType.UNIQUE_GROUP,
        ]:
            # Count distinct values, filtering out null UUIDs and empty strings
            return parse_expr(
                f"""toFloat(count(distinct
                    multiIf(
                        toTypeName({column_ref}) = 'UUID' AND reinterpretAsUInt128({column_ref}) = 0, NULL,
                        toString({column_ref}) = '', NULL,
                        {column_ref}
                    )
                ))"""
            )
        elif math_type == ExperimentMetricMathType.MIN:
            # Outer coalesce ensures 0 (not NULL) when entity has no events of this type
            return parse_expr(f"coalesce(min(toFloat({column_ref})), 0)")
        elif math_type == ExperimentMetricMathType.MAX:
            return parse_expr(f"coalesce(max(toFloat({column_ref})), 0)")
        elif math_type == ExperimentMetricMathType.AVG:
            return parse_expr(f"coalesce(avg(toFloat({column_ref})), 0)")
        elif math_type == ExperimentMetricMathType.HOGQL:
            math_hogql = getattr(source, "math_hogql", None)
            if math_hogql is not None:
                aggregation_function, _, params = extract_aggregation_and_inner_expr(math_hogql)
                if aggregation_function:
                    inner_value_expr = parse_expr(f"toFloat({column_ref})")
                    agg_call = build_aggregation_call(aggregation_function, inner_value_expr, params=params)
                    return ast.Call(name="coalesce", args=[agg_call, ast.Constant(value=0)])
            # Fallback to SUM
            return parse_expr(f"sum(coalesce(toFloat({column_ref}), 0))")
        else:
            # SUM (default) - coalesce is needed here because sum(NULL) returns NULL.
            # For ratio metrics with combined_events, when there are no events of one type,
            # all values for that type are NULL (from UNION ALL structure), and we want 0 not NULL.
            return parse_expr(f"sum(coalesce(toFloat({column_ref}), 0))")

    def _build_test_accounts_filter(self) -> ast.Expr:
        if (
            self.filter_test_accounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            return ast.And(exprs=[property_to_expr(property, self.team) for property in self.team.test_account_filters])
        return ast.Constant(value=True)

    def _build_variant_property(self) -> ast.Field:
        """Derive which event property that should be used for variants"""

        # $feature_flag_called events are special as we can use the $feature_flag_response
        if (
            isinstance(self.exposure_config, ExperimentEventExposureConfig)
            and self.exposure_config.event == "$feature_flag_called"
        ):
            return ast.Field(chain=["properties", "$feature_flag_response"])

        return ast.Field(chain=["properties", f"$feature/{self.feature_flag_key}"])

    def _build_variant_expr_for_funnel(self) -> ast.Expr:
        """
        Builds the variant selection expression based on multiple variant handling.
        """

        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            return parse_expr(
                "argMinIf(variant, timestamp, step_0 = 1)",
            )
        else:
            return parse_expr(
                "if(uniqExactIf(variant, step_0 = 1) > 1, {multiple_key}, anyIf(variant, step_0 = 1))",
                placeholders={
                    "multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )

    def _build_exposure_predicate(self) -> ast.Expr:
        """
        Builds the exposure predicate as an AST expression.
        """
        event_predicate = event_or_action_to_filter(self.team, self.exposure_config)

        # $feature_flag_called events are special. We need to check that the property
        # $feature_flag matches the flag
        if (
            isinstance(self.exposure_config, ExperimentEventExposureConfig)
            and self.exposure_config.event == "$feature_flag_called"
        ):
            flag_property = f"$feature_flag"
            event_predicate = ast.And(
                exprs=[
                    event_predicate,
                    parse_expr(
                        "{flag_property} = {feature_flag_key}",
                        placeholders={
                            "flag_property": ast.Field(chain=["properties", flag_property]),
                            "feature_flag_key": ast.Constant(value=self.feature_flag_key),
                        },
                    ),
                ]
            )

        return _optimize_and_chain(
            parse_expr(
                """
                timestamp >= {date_from}
                AND timestamp <= {date_to}
                AND {event_predicate}
                AND {test_accounts_filter}
                AND {variant_property} IN {variants}
                """,
                placeholders={
                    "date_from": self.date_range_query.date_from_as_hogql(),
                    "date_to": self.date_range_query.date_to_as_hogql(),
                    "event_predicate": event_predicate,
                    "variant_property": self._build_variant_property(),
                    "variants": ast.Constant(value=self.variants),
                    "test_accounts_filter": self._build_test_accounts_filter(),
                },
            )
        )

    def _build_exposure_select_query(self) -> ast.SelectQuery:
        exposure_query = parse_select(
            """
                SELECT
                    {entity_key} AS entity_id,
                    {variant_expr} AS variant,
                    min(timestamp) AS first_exposure_time,
                    max(timestamp) AS last_exposure_time,
                    argMin(uuid, timestamp) AS exposure_event_uuid,
                    argMin(`$session_id`, timestamp) AS exposure_session_id
                    -- breakdown columns added programmatically below
                FROM events
                WHERE {exposure_predicate}
                GROUP BY entity_id
                -- breakdown columns added programmatically below
            """,
            placeholders={
                "entity_key": parse_expr(self.entity_key),
                "variant_expr": self._build_variant_expr_for_mean(),
                "exposure_predicate": self._build_exposure_predicate(),
            },
        )
        assert isinstance(exposure_query, ast.SelectQuery)

        # Inject breakdown columns into the exposure query if needed
        if self._has_breakdown():
            breakdown_exprs = self._build_breakdown_exprs(table_alias="")

            # Add breakdown columns to SELECT using argMin attribution
            # This ensures each user is attributed to exactly one breakdown value
            # (from their first exposure), preventing duplicate counting when users
            # have multiple exposures with different breakdown property values
            for alias, expr in breakdown_exprs:
                # Use argMin to attribute breakdown value from first exposure
                # This matches the variant attribution logic
                breakdown_attributed = parse_expr("argMin({expr}, timestamp)", placeholders={"expr": expr})
                exposure_query.select.append(ast.Alias(alias=alias, expr=breakdown_attributed))

        return exposure_query

    def _build_variant_expr_for_mean(self) -> ast.Expr:
        """
        Builds the variant selection expression for mean metrics based on multiple variant handling.
        """

        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            return parse_expr(
                "argMin({variant_property}, timestamp)",
                placeholders={
                    "variant_property": self._build_variant_property(),
                },
            )
        else:
            return parse_expr(
                "if(uniqExact({variant_property}) > 1, {multiple_key}, any({variant_property}))",
                placeholders={
                    "variant_property": self._build_variant_property(),
                    "multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )

    def _build_funnel_step_columns(self) -> list[ast.Alias]:
        """
        Builds list of step column AST expressions: step_0, step_1, etc.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)

        step_columns: list[ast.Alias] = [ast.Alias(alias="step_0", expr=self._build_exposure_predicate())]

        for i, funnel_step in enumerate(self.metric.series):
            step_filter = event_or_action_to_filter(self.team, funnel_step)
            step_columns.append(
                ast.Alias(
                    alias=f"step_{i + 1}",
                    expr=ast.Call(name="if", args=[step_filter, ast.Constant(value=1), ast.Constant(value=0)]),
                )
            )

        return step_columns

    def _build_funnel_steps_filter(self) -> ast.Expr:
        """
        Returns the expression to filter funnel steps (matches ANY step) within
        the time period of the experiment + the conversion window if set.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)

        conversion_window_seconds = self._get_conversion_window_seconds()
        if conversion_window_seconds > 0:
            date_to = parse_expr(
                "{to_date} + toIntervalSecond({conversion_window_seconds})",
                placeholders={
                    "to_date": self.date_range_query.date_to_as_hogql(),
                    "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                },
            )
        else:
            date_to = self.date_range_query.date_to_as_hogql()

        return parse_expr(
            """
            timestamp >= {date_from} AND timestamp <= {date_to}
            AND {funnel_steps_filter}
            """,
            placeholders={
                "date_from": self.date_range_query.date_from_as_hogql(),
                "date_to": date_to,
                "funnel_steps_filter": funnel_steps_to_filter(self.team, self.metric.series),
            },
        )

    def _build_funnel_aggregation_expr(self) -> ast.Expr:
        """
        Returns the funnel evaluation expression using aggregate_funnel_array.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)
        return funnel_evaluation_expr(self.team, self.metric, events_alias="metric_events", include_exposure=True)

    def _build_uuid_to_session_map(self) -> ast.Expr:
        """
        Creates a map from event UUID to session ID for funnel metrics.
        """
        return parse_expr(
            "mapFromArrays(groupArray(coalesce(toString(metric_events.uuid), '')), groupArray(coalesce(toString(metric_events.session_id), '')))"
        )

    def _build_uuid_to_timestamp_map(self) -> ast.Expr:
        """
        Creates a map from event UUID to timestamp for funnel metrics.
        """
        return parse_expr(
            "mapFromArrays(groupArray(coalesce(toString(metric_events.uuid), '')), groupArray(coalesce(metric_events.timestamp, toDateTime(0))))"
        )

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
        assert isinstance(self.metric, ExperimentRetentionMetric)

        # Build the CTEs
        common_ctes = """
            exposures AS (
                {exposure_select_query}
            ),

            start_events AS (
                SELECT
                    {entity_key} AS entity_id,
                    {start_timestamp_expr} AS start_timestamp
                FROM events
                WHERE {start_event_predicate}
                GROUP BY entity_id
            ),

            completion_events AS (
                SELECT
                    {entity_key} AS entity_id,
                    timestamp AS completion_timestamp
                FROM events
                WHERE {completion_event_predicate}
            ),

            entity_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    MAX(if(
                        completion_events.completion_timestamp IS NOT NULL
                        AND {truncated_completion_timestamp} >= {truncated_start_timestamp} + {retention_window_start_interval}
                        AND {truncated_completion_timestamp} <= {truncated_start_timestamp} + {retention_window_end_interval},
                        1,
                        0
                    )) AS value
                FROM exposures
                INNER JOIN start_events
                    ON exposures.entity_id = start_events.entity_id
                    AND {start_conversion_window_predicate}
                LEFT JOIN completion_events
                    ON exposures.entity_id = completion_events.entity_id
                    AND {completion_retention_window_predicate}
                GROUP BY exposures.entity_id, exposures.variant
            )
        """

        placeholders = {
            "exposure_select_query": self._build_exposure_select_query(),
            "entity_key": parse_expr(self.entity_key),
            "start_timestamp_expr": self._build_start_event_timestamp_expr(),
            "start_event_predicate": self._build_start_event_predicate(),
            "completion_event_predicate": self._build_completion_event_predicate(),
            "retention_window_start_interval": self._build_retention_window_interval(
                self.metric.retention_window_start
            ),
            "retention_window_end_interval": self._build_retention_window_interval(self.metric.retention_window_end),
            "start_conversion_window_predicate": self._build_start_conversion_window_predicate(),
            "completion_retention_window_predicate": self._build_completion_retention_window_predicate(),
            "truncated_start_timestamp": self._get_retention_window_truncation_expr(
                parse_expr("start_events.start_timestamp")
            ),
            "truncated_completion_timestamp": self._get_retention_window_truncation_expr(
                parse_expr("completion_events.completion_timestamp")
            ),
        }

        query = parse_select(
            f"""
            WITH {common_ctes}

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                sum(entity_metrics.value) AS total_sum,
                sum(power(entity_metrics.value, 2)) AS total_sum_of_squares,
                count(entity_metrics.entity_id) AS denominator_sum,
                count(entity_metrics.entity_id) AS denominator_sum_squares,
                sum(entity_metrics.value) AS numerator_denominator_sum_product
            FROM entity_metrics
            WHERE notEmpty(variant)
            GROUP BY entity_metrics.variant
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns if breakdown filter is present
        if self._has_breakdown():
            self._inject_retention_breakdown_columns(query)

        return query

    def _build_start_event_timestamp_expr(self) -> ast.Expr:
        """
        Returns expression to get start event timestamp based on start_handling.
        FIRST_SEEN: Use the first occurrence of start event
        LAST_SEEN: Use the last occurrence of start event
        """
        assert isinstance(self.metric, ExperimentRetentionMetric)

        if self.metric.start_handling == StartHandling.FIRST_SEEN:
            return parse_expr("min(timestamp)")
        else:  # LAST_SEEN
            return parse_expr("max(timestamp)")

    def _get_retention_window_truncation_expr(self, timestamp_expr: ast.Expr) -> ast.Expr:
        """
        Returns truncated timestamp expression for retention window comparisons.

        For DAY: returns toStartOfDay(timestamp)
        For HOUR: returns toStartOfHour(timestamp)
        For other units: returns timestamp unchanged

        This ensures [7,7] day window means "any time on day 7" rather than
        "exactly 7*24 hours after start event to the second".
        """
        assert isinstance(self.metric, ExperimentRetentionMetric)

        # Only truncate DAY and HOUR units for intuitive behavior
        unit_to_interval_name = {
            FunnelConversionWindowTimeUnit.DAY: "day",
            FunnelConversionWindowTimeUnit.HOUR: "hour",
        }

        interval_name = unit_to_interval_name.get(self.metric.retention_window_unit)
        if interval_name is None:
            return timestamp_expr

        return get_start_of_interval_hogql(interval=interval_name, team=self.team, source=timestamp_expr)

    def _build_retention_window_interval(self, window_value: int) -> ast.Expr:
        """
        Converts retention window value to ClickHouse interval expression.
        """
        assert isinstance(self.metric, ExperimentRetentionMetric)

        unit_map = {
            FunnelConversionWindowTimeUnit.SECOND: "Second",
            FunnelConversionWindowTimeUnit.MINUTE: "Minute",
            FunnelConversionWindowTimeUnit.HOUR: "Hour",
            FunnelConversionWindowTimeUnit.DAY: "Day",
            FunnelConversionWindowTimeUnit.WEEK: "Week",
            FunnelConversionWindowTimeUnit.MONTH: "Month",
        }
        unit = unit_map[self.metric.retention_window_unit]
        return parse_expr(
            f"toInterval{unit}({{value}})",
            placeholders={"value": ast.Constant(value=window_value)},
        )

    def _build_start_event_predicate(self) -> ast.Expr:
        """
        Builds the predicate for filtering start events.
        """
        assert isinstance(self.metric, ExperimentRetentionMetric)

        if isinstance(self.metric.start_event, ExperimentDataWarehouseNode):
            event_filter = data_warehouse_node_to_filter(self.team, self.metric.start_event)
        else:
            event_filter = event_or_action_to_filter(self.team, self.metric.start_event)
        conversion_window_seconds = self._get_conversion_window_seconds()

        return parse_expr(
            """
            timestamp >= {date_from}
            AND timestamp < {date_to} + toIntervalSecond({conversion_window_seconds})
            AND {event_filter}
            """,
            placeholders={
                "date_from": self.date_range_query.date_from_as_hogql(),
                "date_to": self.date_range_query.date_to_as_hogql(),
                "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                "event_filter": event_filter,
            },
        )

    def _build_completion_event_predicate(self) -> ast.Expr:
        """
        Builds the predicate for filtering completion events.
        """
        assert isinstance(self.metric, ExperimentRetentionMetric)

        if isinstance(self.metric.completion_event, ExperimentDataWarehouseNode):
            event_filter = data_warehouse_node_to_filter(self.team, self.metric.completion_event)
        else:
            event_filter = event_or_action_to_filter(self.team, self.metric.completion_event)

        # Completion events can occur within the retention window after the start event
        # The retention window end could extend beyond the experiment end date
        conversion_window_seconds = self._get_conversion_window_seconds()
        retention_window_end_seconds = conversion_window_to_seconds(
            self.metric.retention_window_end,
            self.metric.retention_window_unit,
        )

        return parse_expr(
            """
            timestamp >= {date_from}
            AND timestamp < {date_to} + toIntervalSecond({total_window_seconds})
            AND {event_filter}
            """,
            placeholders={
                "date_from": self.date_range_query.date_from_as_hogql(),
                "date_to": self.date_range_query.date_to_as_hogql(),
                "total_window_seconds": ast.Constant(value=conversion_window_seconds + retention_window_end_seconds),
                "event_filter": event_filter,
            },
        )

    def _build_start_conversion_window_predicate(self) -> ast.Expr:
        """
        Builds the predicate for the join condition limiting start events to the conversion window.
        """
        conversion_window_seconds = self._get_conversion_window_seconds()
        if conversion_window_seconds > 0:
            return parse_expr(
                """
                start_events.start_timestamp >= exposures.first_exposure_time
                AND start_events.start_timestamp <= exposures.first_exposure_time + toIntervalSecond({conversion_window_seconds})
                """,
                placeholders={
                    "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                },
            )
        else:
            return parse_expr("start_events.start_timestamp >= exposures.first_exposure_time")

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
        assert isinstance(self.metric, ExperimentRetentionMetric)

        retention_window_end_seconds = conversion_window_to_seconds(
            self.metric.retention_window_end,
            self.metric.retention_window_unit,
        )

        # For DAY/HOUR units, add a buffer to account for truncation
        # This ensures same-period retention windows work correctly
        truncation_buffer = 0
        if self.metric.retention_window_unit == FunnelConversionWindowTimeUnit.DAY:
            # For DAY units, allow completions within the same day (24 hours)
            truncation_buffer = 86400  # 1 day in seconds
        elif self.metric.retention_window_unit == FunnelConversionWindowTimeUnit.HOUR:
            # For HOUR units, allow completions within the same hour
            truncation_buffer = 3600  # 1 hour in seconds

        # Add buffer to retention window end
        buffered_window_end_seconds = retention_window_end_seconds + truncation_buffer

        return parse_expr(
            """
            completion_events.completion_timestamp >= start_events.start_timestamp
            AND completion_events.completion_timestamp <= start_events.start_timestamp + toIntervalSecond({retention_window_end_seconds})
            """,
            placeholders={
                "retention_window_end_seconds": ast.Constant(value=buffered_window_end_seconds),
            },
        )


def _optimize_and_chain(expr: ast.Expr) -> ast.Expr:
    """
    Remove True constants from AND chains to preserve ClickHouse index optimizations.
    Keeps SQL templates readable while avoiding unnecessary conditions.
    """
    if not isinstance(expr, ast.And):
        return expr

    filtered = [e for e in expr.exprs if not (isinstance(e, ast.Constant) and e.value is True)]

    if len(filtered) == 0:
        return ast.Constant(value=True)
    elif len(filtered) == 1:
        return filtered[0]
    else:
        return ast.And(exprs=filtered)
