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
    ExperimentMetricMathType,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    FunnelConversionWindowTimeUnit,
    MultipleVariantHandling,
    StartHandling,
    StepOrderValue,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
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
    is_session_property_metric,
    validate_session_property,
)
from posthog.hogql_queries.experiments.breakdown_injector import BreakdownInjector
from posthog.hogql_queries.experiments.cuped_config import CupedQueryConfig
from posthog.hogql_queries.experiments.exposure_query_logic import normalize_to_exposure_criteria
from posthog.hogql_queries.experiments.funnel_step_builder import FunnelStepBuilder
from posthog.hogql_queries.experiments.hogql_aggregation_utils import (
    aggregation_needs_numeric_input,
    build_aggregation_call,
    extract_aggregation_and_inner_expr,
)
from posthog.hogql_queries.experiments.metric_source import MetricSourceInfo
from posthog.hogql_queries.insights.utils.utils import get_start_of_interval_hogql
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

    # Experiment queries group by (variant, breakdown_values), so the row count is
    # bounded by num_variants × num_breakdown_values.  The HogQL executor injects
    # LIMIT 100 when no explicit limit is set, which silently truncates results for
    # high-cardinality breakdowns.  Set a generous explicit limit to prevent this.
    QUERY_RESULT_LIMIT = MAX_SELECT_RETURNED_ROWS

    def build_query(self) -> ast.SelectQuery:
        """
        Main entry point. Returns complete query built from HogQL with placeholders.
        """
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

    def get_daily_exposures_from_precomputed(self, job_ids: list[str]) -> ast.SelectQuery:
        """
        Reads from the precomputed table and aggregates into day/variant/count.
        Used by the Exposures tab in the experiment UI.
        """
        entity_id_expr = (
            parse_expr("toUUID(t.entity_id)") if self.entity_key == "person_id" else parse_expr("t.entity_id")
        )

        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            variant_expr = parse_expr("argMin(t.variant, t.first_exposure_time)")
        else:
            variant_expr = parse_expr(
                "if(uniqExact(t.variant) > 1, {multiple_key}, argMin(t.variant, t.first_exposure_time))",
                placeholders={"multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY)},
            )

        query = parse_select(
            """
            WITH deduplicated AS (
                SELECT
                    {entity_id_expr} AS entity_id,
                    {variant_expr} AS variant,
                    min(t.first_exposure_time) AS first_exposure_time
                FROM experiment_exposures_preaggregated AS t
                WHERE t.job_id IN {job_ids}
                    AND t.team_id = {team_id}
                    AND t.first_exposure_time >= {date_from}
                    AND t.first_exposure_time <= {date_to}
                GROUP BY entity_id
            )
            SELECT
                toDate(toString(first_exposure_time)) AS day,
                variant AS variant,
                count(entity_id) AS exposed_count
            FROM deduplicated
            WHERE notEmpty(variant)
            GROUP BY day, variant
            ORDER BY day ASC
            """,
            placeholders={
                "entity_id_expr": entity_id_expr,
                "variant_expr": variant_expr,
                "job_ids": ast.Constant(value=job_ids),
                "team_id": ast.Constant(value=self.team.id),
                "date_from": self.date_range_query.date_from_as_hogql(),
                "date_to": self.date_range_query.date_to_as_hogql(),
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

    def _get_maturity_window_seconds(self) -> int:
        """
        Returns the total maturity window in seconds.
        For retention metrics: conversion_window + retention_window_end.
        For other metrics: conversion_window.
        Returns 0 if no conversion window is configured.
        """
        conversion_window_seconds = self._get_conversion_window_seconds()
        if conversion_window_seconds == 0:
            return 0

        if isinstance(self.metric, ExperimentRetentionMetric):
            retention_window_end_seconds = conversion_window_to_seconds(
                self.metric.retention_window_end,
                self.metric.retention_window_unit,
            )
            return conversion_window_seconds + retention_window_end_seconds

        return conversion_window_seconds

    def _build_maturity_having_clause(self, timestamp_expr: str = "timestamp") -> Optional[ast.Expr]:
        """
        Returns a HAVING clause expression to filter out users whose conversion window
        hasn't elapsed yet, or None if the feature is not enabled.
        """
        if self.metric is None:
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

    def _build_funnel_query(self) -> ast.SelectQuery:
        """
        Builds query for funnel metrics.
        Dispatches to optimized (single-scan) or legacy (double-scan) path.
        """
        if self._should_use_optimized_funnel_query():
            return self._build_funnel_query_optimized()
        return self._build_funnel_query_legacy()

    def _should_use_optimized_funnel_query(self) -> bool:
        """
        Returns True when the optimized single-scan funnel query should be used.
        The legacy path is kept for precomputed exposures, where the exposures CTE
        reads from a cheap preaggregated table (no double-scan penalty).
        """
        if self.preaggregation_job_ids and not self.breakdowns:
            return False
        return True

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
        assert isinstance(self.metric, ExperimentFunnelMetric)

        num_steps = len(self.metric.series) + 1  #  +1 as we are including exposure criteria

        # Determine which query pattern to use
        has_dw_steps = self._has_datawarehouse_steps()

        # Track whether step columns need to be injected after parsing.
        # Precomputed metric events already have steps extracted from the array.
        inject_step_columns = True

        if self.metric_events_preaggregation_job_ids and not has_dw_steps:
            # Read from precomputed table instead of scanning events
            inject_step_columns = False
            step_extracts = ", ".join(f"arrayElement(t.steps, {i + 1}) AS step_{i}" for i in range(num_steps))
            entity_id_cast = "toUUID(t.entity_id)" if self.entity_key == "person_id" else "t.entity_id"
            session_id_col = "t.session_id AS session_id," if not self.funnel_steps_data_disabled else ""

            # Filter by experiment date range: jobs can cover broader time ranges
            # than the experiment for cache reusability, so we must filter on read.
            # Upper bound includes conversion window since funnel step events can
            # occur after experiment end.
            conversion_window_seconds = self._get_conversion_window_seconds()
            if conversion_window_seconds > 0:
                upper_bound = f"{{metric_events_date_to}} + toIntervalSecond({conversion_window_seconds})"
            else:
                upper_bound = "{metric_events_date_to}"

            metric_events_cte_str = f"""
                    metric_events AS (
                        SELECT
                            {entity_id_cast} AS entity_id,
                            t.timestamp AS timestamp,
                            t.event_uuid AS uuid,
                            {session_id_col}
                            {step_extracts}
                        FROM experiment_metric_events_preaggregated AS t
                        WHERE t.job_id IN {{metric_events_job_ids}}
                            AND t.team_id = {{metric_events_team_id}}
                            AND t.timestamp >= {{metric_events_date_from}}
                            AND t.timestamp <= {upper_bound}
                    )
            """
        elif has_dw_steps:
            # UNION ALL pattern for heterogeneous sources
            metric_events_cte_str = self._build_funnel_metric_events_cte_with_union()
        else:
            session_id_column = (
                """
                            properties.$session_id AS session_id,"""
                if not self.funnel_steps_data_disabled
                else ""
            )

            metric_events_cte_str = f"""
                    metric_events AS (
                        SELECT
                            {{entity_key}} AS entity_id,
                            {{variant_property}} as variant,
                            timestamp,
                            uuid,{session_id_column}
                            -- step_0, step_1, ... step_N columns added programmatically below
                        FROM events
                        WHERE ({{exposure_predicate}} OR {{funnel_steps_filter}})
                    )
            """

        is_unordered_funnel = self.metric.funnel_order_type == StepOrderValue.UNORDERED

        # Use separate exposures CTE to leverage precomputed exposure cache when available.
        # The exposures query automatically falls back to scanning events if precomputation
        # isn't enabled for the team.
        #
        # Unordered funnels need temporal filtering (metric_events.timestamp >= first_exposure_time)
        # because the funnel UDF doesn't filter out events before the exposure.
        # Ordered funnels don't need this - the UDF handles temporal ordering internally.

        # Build the JOIN clause with conditional temporal filter
        temporal_filter = "AND metric_events.timestamp >= exposures.first_exposure_time" if is_unordered_funnel else ""

        if self.funnel_steps_data_disabled:
            # When steps data is disabled, we skip the expensive session/event maps and
            # the per-exposure columns that are only needed for steps_event_data.
            # The exposures CTE already deduplicates to one row per (entity_id, variant),
            # so removing these from GROUP BY doesn't change results.
            extra_select_columns = ""
            extra_group_by_columns = ""
        else:
            extra_select_columns = """,
                    exposures.exposure_event_uuid AS exposure_event_uuid,
                    exposures.exposure_session_id AS exposure_session_id,
                    exposures.first_exposure_time AS exposure_timestamp,
                    {uuid_to_session_map} AS uuid_to_session,
                    {uuid_to_timestamp_map} AS uuid_to_timestamp"""
            extra_group_by_columns = """,
                    exposures.exposure_event_uuid,
                    exposures.exposure_session_id,
                    exposures.first_exposure_time"""

        ctes_sql = f"""
            exposures AS (
                {{exposure_select_query}}
            ),

            {metric_events_cte_str},

            entity_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    {{funnel_aggregation}} AS value{extra_select_columns}
                FROM exposures
                LEFT JOIN metric_events
                    ON exposures.entity_id = metric_events.entity_id
                    {temporal_filter}  -- Only for unordered: filters out events before exposure
                GROUP BY
                    exposures.entity_id,
                    exposures.variant{extra_group_by_columns}
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
            "exposure_select_query": self._get_exposure_query(),
        }
        if not self.funnel_steps_data_disabled:
            placeholders["uuid_to_session_map"] = self._build_uuid_to_session_map()
            placeholders["uuid_to_timestamp_map"] = self._build_uuid_to_timestamp_map()

        if self.metric_events_preaggregation_job_ids:
            placeholders["metric_events_job_ids"] = ast.Constant(value=self.metric_events_preaggregation_job_ids)
            placeholders["metric_events_team_id"] = ast.Constant(value=self.team.id)
            placeholders["metric_events_date_from"] = self.date_range_query.date_from_as_hogql()
            placeholders["metric_events_date_to"] = self.date_range_query.date_to_as_hogql()

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
        if self.breakdown_injector:
            self.breakdown_injector.inject_funnel_breakdown_columns(query)

        # Inject step columns into the metric_events CTE (skip when precomputed — already extracted)
        if inject_step_columns and query.ctes and "metric_events" in query.ctes:
            metric_events_cte = query.ctes["metric_events"]
            if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
                step_columns = self._build_funnel_step_columns()
                metric_events_cte.expr.select.extend(step_columns)

        # Inject the additional selects we do for getting the data we need to render the funnel chart
        # Add step counts - how many users reached each step
        step_count_exprs = []
        for i in range(1, num_steps):
            step_count_exprs.append(f"countIf(entity_metrics.value.1 >= {i})")
        step_counts_expr = f"tuple({', '.join(step_count_exprs)}) as step_counts"

        query.select.append(parse_expr(step_counts_expr))

        # For each step in the funnel, get at least 100 tuples of person_id, session_id, event uuid, and timestamp, that have
        # that step as their last step in the funnel.
        # For the users that have 0 matching steps in the funnel (-1), we return the event data for the exposure event.
        # This is skipped when funnel_steps_data_disabled is set, as it's expensive for high-traffic experiments.
        if not self.funnel_steps_data_disabled:
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
            query.select.append(parse_expr(event_uuids_exprs_sql))

        return query

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
        assert isinstance(self.metric, ExperimentFunnelMetric)

        num_steps = len(self.metric.series) + 1  # +1 as we are including exposure criteria

        session_id_column = (
            """
                        properties.$session_id AS session_id,"""
            if not self.funnel_steps_data_disabled
            else ""
        )

        # CTE 1: base_events - single scan of events table
        # WHERE admits both exposure and conversion events. Exclusion filters are
        # embedded in step_0 only, not the WHERE clause, so conversion events from
        # internal users pass through (they only matter if the user has a valid exposure).
        base_events_cte_str = f"""
                base_events AS (
                    SELECT
                        {{entity_key}} AS entity_id,
                        {{variant_property}} AS variant_value,
                        timestamp,
                        uuid,{session_id_column}
                        -- step_0, step_1, ... step_N columns added programmatically below
                    FROM events
                    WHERE ({{exposure_predicate}} OR {{funnel_steps_filter}})
                )
        """

        is_unordered_funnel = self.metric.funnel_order_type == StepOrderValue.UNORDERED

        # CTE 2: entity_metrics - GROUP BY entity_id, no JOIN
        if self.funnel_steps_data_disabled:
            extra_select_columns = ""
        else:
            extra_select_columns = """,
                    argMinIf(uuid, timestamp, step_0 = 1) AS exposure_event_uuid,
                    argMinIf(session_id, timestamp, step_0 = 1) AS exposure_session_id,
                    minIf(timestamp, step_0 = 1) AS exposure_timestamp,
                    {uuid_to_session_map} AS uuid_to_session,
                    {uuid_to_timestamp_map} AS uuid_to_timestamp"""

        # Unordered funnels need temporal filtering: the UDF doesn't enforce that
        # step_0 (exposure) happens before step_1..N, so we must exclude events
        # before first exposure. Add a lightweight first_exposures sub-CTE.
        if is_unordered_funnel:
            first_exposures_cte_str = """
            first_exposures AS (
                SELECT entity_id, min(timestamp) AS first_exposure_time
                FROM base_events
                WHERE step_0 = 1
                GROUP BY entity_id
            ),"""
            temporal_join = """INNER JOIN first_exposures
                    ON base_events.entity_id = first_exposures.entity_id
                WHERE base_events.timestamp >= first_exposures.first_exposure_time"""
            # INNER JOIN implicitly filters to exposed entities, no HAVING needed
            having_clause = ""
        else:
            first_exposures_cte_str = ""
            temporal_join = ""
            having_clause = """
                HAVING countIf(step_0 = 1) > 0"""

        ctes_sql = f"""
            {base_events_cte_str},
            {first_exposures_cte_str}
            entity_metrics AS (
                SELECT
                    base_events.entity_id AS entity_id,
                    {{variant_expr}} AS variant,
                    {{funnel_aggregation}} AS value{extra_select_columns}
                FROM base_events
                {temporal_join}
                GROUP BY base_events.entity_id{having_clause}
            )
        """

        placeholders: dict[str, ast.Expr | ast.SelectQuery] = {
            "exposure_predicate": self._build_exposure_predicate(),
            "variant_property": self._build_variant_property(),
            "variant_expr": self._build_variant_expr_for_funnel_optimized(),
            "entity_key": parse_expr(self.entity_key),
            "funnel_steps_filter": self._build_funnel_steps_filter(),
            "funnel_aggregation": self._build_funnel_aggregation_expr_optimized(),
            "num_steps_minus_1": ast.Constant(value=num_steps - 1),
        }
        if not self.funnel_steps_data_disabled:
            placeholders["uuid_to_session_map"] = self._build_uuid_to_session_map_optimized()
            placeholders["uuid_to_timestamp_map"] = self._build_uuid_to_timestamp_map_optimized()

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
        if self.breakdown_injector:
            self.breakdown_injector.inject_funnel_breakdown_columns_optimized(query)

        # Inject step columns into the base_events CTE
        if query.ctes and "base_events" in query.ctes:
            base_events_cte = query.ctes["base_events"]
            if isinstance(base_events_cte, ast.CTE) and isinstance(base_events_cte.expr, ast.SelectQuery):
                step_columns = self._build_funnel_step_columns()
                base_events_cte.expr.select.extend(step_columns)

        # Inject maturity HAVING clause into entity_metrics CTE
        # Use maxIf to only consider exposure events for maturity
        maturity_having = self._build_maturity_having_clause_optimized()
        if maturity_having is not None:
            if query.ctes and "entity_metrics" in query.ctes:
                entity_metrics_cte = query.ctes["entity_metrics"]
                if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                    if entity_metrics_cte.expr.having is None:
                        entity_metrics_cte.expr.having = maturity_having
                    else:
                        entity_metrics_cte.expr.having = ast.And(
                            exprs=[entity_metrics_cte.expr.having, maturity_having]
                        )

        # Add step counts - how many users reached each step
        step_count_exprs = []
        for i in range(1, num_steps):
            step_count_exprs.append(f"countIf(entity_metrics.value.1 >= {i})")
        step_counts_expr = f"tuple({', '.join(step_count_exprs)}) as step_counts"

        query.select.append(parse_expr(step_counts_expr))

        # For each step in the funnel, get sample tuples of person_id, session_id, event uuid, and timestamp
        if not self.funnel_steps_data_disabled:
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
            query.select.append(parse_expr(event_uuids_exprs_sql))

        return query

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
            exposure_query.select.append(
                ast.Alias(
                    alias="exposure_identifier",
                    expr=ast.Field(chain=events_join_key_parts),
                )
            )
            if exposure_query.group_by:
                exposure_query.group_by.append(ast.Field(chain=events_join_key_parts))

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
                exposure_query.select.append(
                    ast.Alias(
                        alias="exposure_identifier_num",
                        expr=ast.Field(chain=num_join_key_parts),
                    )
                )
                if exposure_query.group_by:
                    exposure_query.group_by.append(ast.Field(chain=num_join_key_parts))

            if denom_source_info.kind == "datawarehouse":
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
                "num_entity_key": num_entity_field,
                "denom_entity_key": denom_entity_field,
                "num_timestamp_field": ast.Field(chain=[num_timestamp_field]),
                "num_table": ast.Field(chain=[num_table]),
                "denom_timestamp_field": ast.Field(chain=[denom_timestamp_field]),
                "denom_table": ast.Field(chain=[denom_table]),
                "numerator_predicate": self._build_metric_predicate(
                    source=self.metric.numerator, table_alias=num_table
                ),
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
                "denominator_conversion_window": self._build_conversion_window_predicate_for_events(
                    "denominator_events"
                ),
            },
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns into the query AST
        if self.breakdown_injector:
            self.breakdown_injector.inject_ratio_breakdown_columns(query)

        return query

    def _build_conversion_window_predicate(self) -> ast.Expr:
        """
        Build the predicate for limiting metric events to the conversion window for the user.
        Uses "metric_events" as the events alias.
        """
        return self._build_conversion_window_predicate_for_events("metric_events")

    def _build_session_conversion_window_predicate(self) -> ast.Expr:
        """
        Build the predicate for limiting session metric events to the conversion window.
        Uses first_event_timestamp from metric_events_by_session for temporal filtering.
        """
        conversion_window_seconds = self._get_conversion_window_seconds()
        if conversion_window_seconds > 0:
            return parse_expr(
                """
                metric_events_by_session.first_event_timestamp
                    < exposures.last_exposure_time + toIntervalSecond({conversion_window_seconds})
                """,
                placeholders={
                    "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                },
            )
        else:
            # No conversion window limit - just return true since temporal filtering
            # is already handled by the >= first_exposure_timestamp condition in the join
            return ast.Constant(value=True)

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

    def _build_cuped_pre_window_predicate(self, events_alias: str = "metric_events") -> ast.Expr:
        return parse_expr(
            f"""
            {events_alias}.timestamp >= exposures.first_exposure_time - toIntervalDay({{lookback_days}})
            AND {events_alias}.timestamp < exposures.first_exposure_time
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
        date_from = self.date_range_query.date_from_as_hogql()
        if cuped_lookback_days is not None:
            date_from = parse_expr(
                "{date_from} - toIntervalDay({lookback_days})",
                placeholders={
                    "date_from": date_from,
                    "lookback_days": ast.Constant(value=cuped_lookback_days),
                },
            )

        return parse_expr(
            """
            {timestamp_field} >= {date_from}
            AND {timestamp_field} < {date_to} + toIntervalSecond({conversion_window_seconds})
            AND {metric_event_filter}
            """,
            placeholders={
                "timestamp_field": ast.Field(chain=timestamp_field_chain),
                "date_from": date_from,
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

        # Don't coalesce values for count distinct types (IDs) or HOGQL (user controls the expression)
        math_type = getattr(source, "math", ExperimentMetricMathType.TOTAL)
        if math_type in [
            ExperimentMetricMathType.UNIQUE_SESSION,
            ExperimentMetricMathType.DAU,
            ExperimentMetricMathType.UNIQUE_GROUP,
            ExperimentMetricMathType.HOGQL,
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

        math_type = getattr(source, "math", ExperimentMetricMathType.TOTAL)
        column_ref = f"{events_alias}.{column_name}"

        if math_type in [
            ExperimentMetricMathType.UNIQUE_SESSION,
            ExperimentMetricMathType.DAU,
            ExperimentMetricMathType.UNIQUE_GROUP,
        ]:
            if value_expr is not None:
                # Count distinct values, filtering out null UUIDs and empty strings.
                # Conditional CUPED expressions can be Nullable, so handle NULL before
                # applying the same empty-value filtering as the base path.
                return parse_expr(
                    """toFloat(count(distinct
                        multiIf(
                            isNull({value_expr}), NULL,
                            toTypeName({value_expr}) IN ('UUID', 'Nullable(UUID)') AND reinterpretAsUInt128(assumeNotNull({value_expr})) = 0, NULL,
                            toString({value_expr}) = '', NULL,
                            {value_expr}
                        )
                    ))""",
                    placeholders={"value_expr": value_expr},
                )

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
            if value_expr is not None:
                return parse_expr("coalesce(min(toFloat({value_expr})), 0)", placeholders={"value_expr": value_expr})
            return parse_expr(f"coalesce(min(toFloat({column_ref})), 0)")
        elif math_type == ExperimentMetricMathType.MAX:
            if value_expr is not None:
                return parse_expr("coalesce(max(toFloat({value_expr})), 0)", placeholders={"value_expr": value_expr})
            return parse_expr(f"coalesce(max(toFloat({column_ref})), 0)")
        elif math_type == ExperimentMetricMathType.AVG:
            if value_expr is not None:
                return parse_expr("coalesce(avg(toFloat({value_expr})), 0)", placeholders={"value_expr": value_expr})
            return parse_expr(f"coalesce(avg(toFloat({column_ref})), 0)")
        elif math_type == ExperimentMetricMathType.HOGQL:
            math_hogql = getattr(source, "math_hogql", None)
            if math_hogql is not None:
                aggregation_function, _, params, distinct = extract_aggregation_and_inner_expr(math_hogql)
                if aggregation_function:
                    inner_value_expr = value_expr or parse_expr(column_ref)
                    if aggregation_needs_numeric_input(aggregation_function):
                        inner_value_expr = ast.Call(name="toFloat", args=[inner_value_expr])
                    agg_call = build_aggregation_call(
                        aggregation_function, inner_value_expr, params=params, distinct=distinct
                    )
                    # Non-numeric aggregations (count, uniq, etc.) return UInt64, which is
                    # incompatible with Float64 in ClickHouse greatest/least functions used
                    # by winsorization. Wrap with toFloat to ensure consistent Float64 type.
                    if not aggregation_needs_numeric_input(aggregation_function):
                        agg_call = ast.Call(name="toFloat", args=[agg_call])
                    return ast.Call(name="coalesce", args=[agg_call, ast.Constant(value=0)])
            # Fallback to SUM
            if value_expr is not None:
                return parse_expr("sum(coalesce(toFloat({value_expr}), 0))", placeholders={"value_expr": value_expr})
            return parse_expr(f"sum(coalesce(toFloat({column_ref}), 0))")
        else:
            # SUM (default) - coalesce is needed here because sum(NULL) returns NULL.
            # For ratio metrics with combined_events, when there are no events of one type,
            # all values for that type are NULL (from UNION ALL structure), and we want 0 not NULL.
            if value_expr is not None:
                return parse_expr("sum(coalesce(toFloat({value_expr}), 0))", placeholders={"value_expr": value_expr})
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

    def _build_exposure_event_predicate(self) -> ast.Expr:
        """
        Builds the event predicate for exposure filtering (without timestamp conditions).

        This handles:
        - Custom exposure events via event_or_action_to_filter
        - Special $feature_flag_called filtering (matching the flag key)

        Used by both _build_exposure_predicate() and get_exposure_query_for_precomputation().
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

        return event_predicate

    def _build_exposure_predicate(self) -> ast.Expr:
        """
        Builds the exposure predicate as an AST expression.
        """
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
                    "event_predicate": self._build_exposure_event_predicate(),
                    "variant_property": self._build_variant_property(),
                    "variants": ast.Constant(value=self.variants),
                    "test_accounts_filter": self._build_test_accounts_filter(),
                },
            )
        )

    def _get_exposure_query(self) -> ast.SelectQuery:
        if self.preaggregation_job_ids and not self.breakdowns:
            return self._build_exposure_from_precomputed(self.preaggregation_job_ids)

        return self._build_exposure_select_query()

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
        if self.breakdown_injector:
            breakdown_exprs = self.breakdown_injector.build_breakdown_exprs(table_alias="")

            # Add breakdown columns to SELECT using argMin attribution
            # This ensures each user is attributed to exactly one breakdown value
            # (from their first exposure), preventing duplicate counting when users
            # have multiple exposures with different breakdown property values
            for alias, expr in breakdown_exprs:
                # Use argMin to attribute breakdown value from first exposure
                # This matches the variant attribution logic
                breakdown_attributed = parse_expr("argMin({expr}, timestamp)", placeholders={"expr": expr})
                exposure_query.select.append(ast.Alias(alias=alias, expr=breakdown_attributed))

        # Filter out users whose conversion window hasn't elapsed yet
        maturity_having = self._build_maturity_having_clause()
        if maturity_having is not None:
            if exposure_query.having is None:
                exposure_query.having = maturity_having
            else:
                exposure_query.having = ast.And(exprs=[exposure_query.having, maturity_having])

        return exposure_query

    def _build_exposure_from_precomputed(self, job_ids: list[str]) -> ast.SelectQuery:
        """
        Builds the exposure CTE by reading from the lazy-computed table instead of scanning events.

        Re-aggregates across jobs since the same user can appear in multiple time-window jobs.
        Returns the same column shape as _build_exposure_select_query().

        Important: Jobs can cover broader time ranges than the experiment (for reusability),
        so we must filter by experiment start/end dates to avoid including exposures outside
        the experiment window.
        """
        # The lazy-computed table stores entity_id as String, but person_id is UUID in events.
        # Cast back to match the type expected by downstream JOINs.
        entity_id_expr = (
            parse_expr("toUUID(t.entity_id)") if self.entity_key == "person_id" else parse_expr("t.entity_id")
        )

        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            variant_expr = parse_expr("argMin(t.variant, t.first_exposure_time)")
        else:
            variant_expr = parse_expr(
                "if(uniqExact(t.variant) > 1, {multiple_key}, argMin(t.variant, t.first_exposure_time))",
                placeholders={"multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY)},
            )

        query = parse_select(
            """
                SELECT
                    {entity_id_expr} AS entity_id,
                    {variant_expr} AS variant,
                    min(t.first_exposure_time) AS first_exposure_time,
                    max(t.last_exposure_time) AS last_exposure_time,
                    argMin(t.exposure_event_uuid, t.first_exposure_time) AS exposure_event_uuid,
                    argMin(t.exposure_session_id, t.first_exposure_time) AS exposure_session_id
                FROM experiment_exposures_preaggregated AS t
                WHERE t.job_id IN {job_ids}
                    AND t.team_id = {team_id}
                    AND t.first_exposure_time >= {date_from}
                    AND t.first_exposure_time <= {date_to}
                GROUP BY entity_id
            """,
            placeholders={
                "entity_id_expr": entity_id_expr,
                "variant_expr": variant_expr,
                "job_ids": ast.Constant(value=job_ids),
                "team_id": ast.Constant(value=self.team.id),
                "date_from": self.date_range_query.date_from_as_hogql(),
                "date_to": self.date_range_query.date_to_as_hogql(),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        # Filter out users whose conversion window hasn't elapsed yet
        maturity_having = self._build_maturity_having_clause(timestamp_expr="t.last_exposure_time")
        if maturity_having is not None:
            if query.having is None:
                query.having = maturity_having
            else:
                query.having = ast.And(exprs=[query.having, maturity_having])

        return query

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
        # Query template with placeholders
        # Note: uses < for time_window_max (exclusive end for bucket boundaries)
        # vs <= in normal query (inclusive end for experiment boundary)
        # Keep in sync with _build_exposure_select_query
        #
        # The time_window_min/max placeholders define the job's cache window
        # (UTC-day-aligned). The experiment_date_from/to placeholders tighten
        # the scan to the actual experiment dates so that variant aggregation
        # only considers events within the experiment.
        query_string = """
            SELECT
                {entity_key} AS entity_id,
                {variant_expr} AS variant,
                min(timestamp) AS first_exposure_time,
                max(timestamp) AS last_exposure_time,
                argMin(uuid, timestamp) AS exposure_event_uuid,
                argMin(`$session_id`, timestamp) AS exposure_session_id,
                [] AS breakdown_value
            FROM events
            WHERE timestamp >= {time_window_min}
                AND timestamp < {time_window_max}
                AND timestamp >= {experiment_date_from}
                AND timestamp <= {experiment_date_to}
                AND {event_predicate}
                AND {test_accounts_filter}
                AND {variant_property} IN {variants}
            GROUP BY entity_id
        """

        placeholders = {
            "entity_key": parse_expr(self.entity_key),
            "variant_expr": self._build_variant_expr_for_mean(),
            "event_predicate": self._build_exposure_event_predicate(),
            "test_accounts_filter": self._build_test_accounts_filter(),
            "variant_property": self._build_variant_property(),
            "variants": ast.Constant(value=self.variants),
            "experiment_date_from": self.date_range_query.date_from_as_hogql(),
            "experiment_date_to": self.date_range_query.date_to_as_hogql(),
        }

        return query_string, placeholders

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
        assert isinstance(self.metric, ExperimentFunnelMetric)

        # Build step indicator expressions for the steps array.
        # step_0 = exposure predicate, step_1..N = funnel step filters.
        # These are the same expressions used in build_boolean_columns().
        exposure_filter = self._build_exposure_predicate()
        step_exprs: list[ast.Expr] = [exposure_filter]

        step_builder = FunnelStepBuilder(self.metric.series, self.team)
        for _step_index, step_source in enumerate(self.metric.series, start=1):
            step_filter = step_builder._build_step_filter(step_source)
            step_exprs.append(step_filter)

        # Pack into Array(UInt8): [toUInt8(if(step_0, 1, 0)), toUInt8(if(step_1, 1, 0)), ...]
        steps_array = ast.Array(
            exprs=[
                ast.Call(
                    name="toUInt8",
                    args=[ast.Call(name="if", args=[expr, ast.Constant(value=1), ast.Constant(value=0)])],
                )
                for expr in step_exprs
            ]
        )

        query_string = """
            SELECT
                {entity_key} AS entity_id,
                timestamp AS timestamp,
                uuid AS event_uuid,
                `$session_id` AS session_id,
                {steps_array} AS steps
            FROM events
            WHERE timestamp >= {time_window_min}
                AND timestamp < {time_window_max}
                AND ({exposure_predicate} OR {funnel_steps_filter})
        """

        placeholders: dict[str, ast.Expr] = {
            "entity_key": parse_expr(self.entity_key),
            "steps_array": steps_array,
            "exposure_predicate": exposure_filter,
            "funnel_steps_filter": self._build_funnel_steps_filter(),
        }

        return query_string, placeholders

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

        # Check if any step is a data warehouse node
        has_dw_nodes = any(isinstance(step, ExperimentDataWarehouseNode) for step in self.metric.series)

        if has_dw_nodes:
            raise NotImplementedError(
                "ExperimentDataWarehouseNode is not yet supported in funnel metrics. "
                "Mixed-source UNION ALL query pattern needs to be implemented."
            )

        # Use FunnelStepBuilder abstraction for boolean columns
        step_builder = FunnelStepBuilder(self.metric.series, self.team)
        exposure_filter = self._build_exposure_predicate()
        return step_builder.build_boolean_columns(exposure_filter)

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

    def _has_datawarehouse_steps(self) -> bool:
        """
        Check if funnel metric has any datawarehouse steps.

        Returns:
            True if any step in the series is ExperimentDataWarehouseNode
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)
        return any(isinstance(step, ExperimentDataWarehouseNode) for step in self.metric.series)

    def _build_funnel_metric_events_cte_with_union(self) -> str:
        """
        Build metric_events CTE using UNION ALL pattern for funnels with DW steps.

        TODO: Full implementation requires:
        1. Building step-specific filters for each subquery (event_or_action_to_filter for events, property filters for DW)
        2. Building constant step columns for each subquery (using FunnelStepBuilder.build_constant_columns)
        3. Handling timestamp filtering within conversion window
        4. Ensuring all subqueries have compatible schema (entity_id as String, placeholder uuid/session_id for DW)

        Pattern:
        - Exposure subquery (step_0=1, others=0): SELECT FROM events WHERE exposure_predicate
        - Each event/action step subquery (step_N=1, others=0): SELECT FROM events WHERE step_filter
        - Each DW step subquery (step_N=1, others=0): SELECT FROM dw_table WHERE timestamp_filter AND property_filters

        For now, raise NotImplementedError to prevent runtime errors.
        """
        raise NotImplementedError(
            "UNION ALL pattern for datawarehouse funnel steps not yet fully implemented. "
            "The abstractions (FunnelStepBuilder, MetricSourceInfo, FunnelDWValidator) are in place. "
            "See experiment_query_builder.py:_build_funnel_metric_events_cte_with_union for implementation TODO."
        )

    # --- Optimized funnel query helpers ---

    def _build_variant_expr_for_funnel_optimized(self) -> ast.Expr:
        """
        Variant expression for the optimized funnel path.
        References variant_value (raw property) instead of variant (column in legacy metric_events).
        """
        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            return parse_expr(
                "argMinIf(variant_value, timestamp, step_0 = 1)",
            )
        else:
            return parse_expr(
                "if(uniqExactIf(variant_value, step_0 = 1) > 1, {multiple_key}, anyIf(variant_value, step_0 = 1))",
                placeholders={
                    "multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )

    def _build_funnel_aggregation_expr_optimized(self) -> ast.Expr:
        """
        Funnel aggregation for the optimized path. References base_events instead of metric_events.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)
        return funnel_evaluation_expr(self.team, self.metric, events_alias="base_events", include_exposure=True)

    def _build_uuid_to_session_map_optimized(self) -> ast.Expr:
        """
        UUID-to-session map for the optimized path. References base_events columns.
        """
        return parse_expr(
            "mapFromArrays(groupArray(coalesce(toString(uuid), '')), groupArray(coalesce(toString(session_id), '')))"
        )

    def _build_uuid_to_timestamp_map_optimized(self) -> ast.Expr:
        """
        UUID-to-timestamp map for the optimized path. References base_events columns.
        """
        return parse_expr(
            "mapFromArrays(groupArray(coalesce(toString(uuid), '')), groupArray(coalesce(timestamp, toDateTime(0))))"
        )

    def _build_maturity_having_clause_optimized(self) -> Optional[ast.Expr]:
        """
        Maturity HAVING clause for the optimized path.
        Uses maxIf to only consider exposure events (step_0 = 1) for maturity,
        since entity_metrics groups over all events, not just exposures.
        """
        if self.metric is None:
            return None
        if not self.only_count_matured_users:
            return None

        maturity_seconds = self._get_maturity_window_seconds()
        if maturity_seconds == 0:
            return None

        now = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        return parse_expr(
            "maxIf(timestamp, step_0 = 1) + toIntervalSecond({maturity_seconds}) <= toDateTime({now}, 'UTC')",
            placeholders={
                "maturity_seconds": ast.Constant(value=maturity_seconds),
                "now": ast.Constant(value=now),
            },
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
                    exposures.entity_id AS entity_id,
                    {start_timestamp_expr} AS start_timestamp
                FROM events
                INNER JOIN exposures ON {entity_key} = exposures.entity_id
                WHERE {start_event_predicate}
                    AND {start_after_exposure_predicate}
                GROUP BY exposures.entity_id
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
                LEFT JOIN completion_events
                    ON exposures.entity_id = completion_events.entity_id
                    AND {completion_retention_window_predicate}
                GROUP BY exposures.entity_id, exposures.variant
            )
        """

        placeholders = {
            "exposure_select_query": self._get_exposure_query(),
            "entity_key": parse_expr(self.entity_key),
            "start_timestamp_expr": self._build_start_event_timestamp_expr(),
            "start_event_predicate": self._build_start_event_predicate(),
            "completion_event_predicate": self._build_completion_event_predicate(),
            "retention_window_start_interval": self._build_retention_window_interval(
                self.metric.retention_window_start
            ),
            "retention_window_end_interval": self._build_retention_window_interval(self.metric.retention_window_end),
            "start_after_exposure_predicate": self._build_start_after_exposure_predicate(),
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
        if self.breakdown_injector:
            self.breakdown_injector.inject_retention_breakdown_columns(query)

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

    def _build_start_after_exposure_predicate(self) -> ast.Expr:
        """
        Builds the predicate for filtering start events to only those after exposure.
        Applied inside the start_events CTE (pre-aggregation) so that min/max only
        considers events after the user's first exposure.
        """
        conversion_window_seconds = self._get_conversion_window_seconds()
        if conversion_window_seconds > 0:
            return parse_expr(
                """
                timestamp >= exposures.first_exposure_time
                AND timestamp <= exposures.first_exposure_time + toIntervalSecond({conversion_window_seconds})
                """,
                placeholders={
                    "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                },
            )
        else:
            return parse_expr("timestamp >= exposures.first_exposure_time")

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
