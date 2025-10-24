from posthog.schema import (
    ActionsNode,
    EventsNode,
    ExperimentEventExposureConfig,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    MultipleVariantHandling,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.experiments.base_query_utils import (
    conversion_window_to_seconds,
    event_or_action_to_filter,
    funnel_evaluation_expr,
    funnel_steps_to_filter,
    get_source_value_expr,
)
from posthog.hogql_queries.experiments.exposure_query_logic import normalize_to_exposure_criteria
from posthog.hogql_queries.experiments.hogql_aggregation_utils import extract_aggregation_and_inner_expr
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Experiment
from posthog.models.team.team import Team


def get_exposure_config_params_for_builder(
    experiment: Experiment,
) -> tuple[ExperimentEventExposureConfig | ActionsNode, MultipleVariantHandling, bool]:
    """A helper function that takes an experiment and returns some of the required parameters for the query builder.

    This is to decouple the relation a bit between experiments and the builder it self. The builder shouldn't need to know this
    experiment specific stuff.
    """
    criteria = normalize_to_exposure_criteria(experiment.exposure_criteria)
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
        metric: ExperimentMeanMetric | ExperimentFunnelMetric,
        exposure_config: ExperimentEventExposureConfig | ActionsNode,
        filter_test_accounts: bool,
        multiple_variant_handling: MultipleVariantHandling,
        variants: list[str],
        date_range_query: QueryDateRange,
        entity_key: str,
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

    def build_query(self) -> ast.SelectQuery:
        """
        Main entry point. Returns complete query built from HogQL with placeholders.
        """
        match self.metric:
            case ExperimentFunnelMetric():
                return self._build_funnel_query()
            case ExperimentMeanMetric():
                return self._build_mean_query()
            case _:
                raise NotImplementedError(f"Only funnel and mean metrics are supported. Got {type(self.metric)}")

    def _get_conversion_window_seconds(self) -> int:
        """
        Returns the conversion window in seconds for the current metric.
        Returns 0 if no conversion window is configured.
        """
        if self.metric.conversion_window and self.metric.conversion_window_unit:
            return conversion_window_to_seconds(
                self.metric.conversion_window,
                self.metric.conversion_window_unit,
            )
        return 0

    def _build_funnel_query(self) -> ast.SelectQuery:
        """
        Builds query for funnel metrics.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)

        num_steps = len(self.metric.series) + 1  #  +1 as we are including exposure criteria

        query = parse_select(
            f"""
            WITH metric_events AS (
                SELECT
                    {{entity_key}} AS entity_id,
                    {{variant_property}} as variant,
                    timestamp,
                    uuid,
                    properties.$session_id AS session_id,
                    -- step_0, step_1, ... step_N columns added programmatically below
                FROM events
                WHERE ({{exposure_predicate}} OR {{funnel_steps_filter}})
            ),

            entity_metrics AS (
                SELECT
                    entity_id,
                    {{variant_expr}} as variant,
                    argMinIf(uuid, timestamp, step_0 = 1) AS exposure_event_uuid,
                    argMinIf(session_id, timestamp, step_0 = 1) AS exposure_session_id,
                    {{funnel_aggregation}} AS value,
                    {{uuid_to_session_map}} AS uuid_to_session
                FROM metric_events
                GROUP BY entity_id
            )

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                -- The return value from the funnel eval is zero indexed. So reaching first step means
                -- it return 0, and so on. So reaching the last step means it will return
                -- num_steps - 1
                countIf(entity_metrics.value.1 = {{num_steps_minus_1}}) AS total_sum,
                countIf(entity_metrics.value.1 = {{num_steps_minus_1}}) AS total_sum_of_squares
                -- step_counts added programatically below
                -- steps_event_data added programatically below
            FROM entity_metrics
            WHERE notEmpty(variant)
            GROUP BY entity_metrics.variant
            """,
            placeholders={
                "exposure_predicate": self._build_exposure_predicate(),
                "variant_property": self._build_variant_property(),
                "variant_expr": self._build_variant_expr_for_funnel(),
                "entity_key": parse_expr(self.entity_key),
                "funnel_steps_filter": self._build_funnel_steps_filter(),
                "funnel_aggregation": self._build_funnel_aggregation_expr(),
                "num_steps_minus_1": ast.Constant(value=num_steps - 1),
                "uuid_to_session_map": self._build_uuid_to_session_map(),
            },
        )

        assert isinstance(query, ast.SelectQuery)

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

        # For each step in the funnel, get at least 100 pairs of person_id, session_id and event uuid, that have
        # that step as their last step in the funnel.
        # For the users that have 0 matching steps in the funnel (-1), we return the event uuid for the exposure event.
        event_uuids_exprs = []
        for i in range(1, num_steps + 1):
            event_uuids_expr = f"""
                groupArraySampleIf(100)(
                    if(
                        entity_metrics.value.2 != '',
                        tuple(toString(entity_metrics.entity_id), uuid_to_session[entity_metrics.value.2], entity_metrics.value.2),
                        tuple(toString(entity_metrics.entity_id), toString(entity_metrics.exposure_session_id), toString(entity_metrics.exposure_event_uuid))
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
        """
        return """
            exposures AS (
                {exposure_select_query}
            ),

            metric_events AS (
                SELECT
                    {entity_key} AS entity_id,
                    timestamp,
                    {value_expr} AS value
                FROM events
                WHERE {metric_predicate}
            ),

            entity_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    {value_agg} AS value
                FROM exposures
                LEFT JOIN metric_events ON exposures.entity_id = metric_events.entity_id
                    AND {conversion_window_predicate}
                GROUP BY exposures.entity_id, exposures.variant
            )
        """

    def _get_mean_query_common_placeholders(self) -> dict:
        """
        Returns the common placeholders used by both regular and winsorized mean queries.
        """
        return {
            "exposure_select_query": self._build_exposure_select_query(),
            "entity_key": parse_expr(self.entity_key),
            "metric_predicate": self._build_metric_predicate(),
            "value_expr": self._build_value_expr(),
            "value_agg": self._build_value_aggregation_expr(),
            "conversion_window_predicate": self._build_conversion_window_predicate(),
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

        query = parse_select(
            f"""
            WITH {common_ctes}

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                sum(entity_metrics.value) AS total_sum,
                sum(power(entity_metrics.value, 2)) AS total_sum_of_squares
            FROM entity_metrics
            GROUP BY entity_metrics.variant
            """,
            placeholders=self._get_mean_query_common_placeholders(),
        )

        assert isinstance(query, ast.SelectQuery)
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
                FROM entity_metrics
            ),

            winsorized_entity_metrics AS (
                SELECT
                    entity_metrics.entity_id AS entity_id,
                    entity_metrics.variant AS variant,
                    least(greatest(percentiles.lower_bound, entity_metrics.value), percentiles.upper_bound) AS value
                FROM entity_metrics
                CROSS JOIN percentiles
            )

            SELECT
                winsorized_entity_metrics.variant AS variant,
                count(winsorized_entity_metrics.entity_id) AS num_users,
                sum(winsorized_entity_metrics.value) AS total_sum,
                sum(power(winsorized_entity_metrics.value, 2)) AS total_sum_of_squares
            FROM winsorized_entity_metrics
            GROUP BY winsorized_entity_metrics.variant
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    def _build_conversion_window_predicate(self) -> ast.Expr:
        """
        Build the predicate for limiting metric events to the conversion window for the user.
        """
        conversion_window_seconds = self._get_conversion_window_seconds()
        if conversion_window_seconds > 0:
            return parse_expr(
                """
                metric_events.timestamp >= exposures.first_exposure_time
                AND metric_events.timestamp < exposures.first_exposure_time + toIntervalSecond({conversion_window_seconds})
                """,
                placeholders={
                    "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                },
            )
        else:
            return parse_expr("metric_events.timestamp >= exposures.first_exposure_time")

    def _build_metric_predicate(self) -> ast.Expr:
        """
        Builds the metric predicate as an AST expression.
        """

        assert isinstance(self.metric, ExperimentMeanMetric)

        # TODO: Implement support for DatawarehouseNode
        assert isinstance(self.metric.source, EventsNode | ActionsNode)

        metric_event_filter = event_or_action_to_filter(self.team, self.metric.source)

        conversion_window_seconds = self._get_conversion_window_seconds()

        return parse_expr(
            """
            timestamp >= {date_from}
            AND timestamp < {date_to} + toIntervalSecond({conversion_window_seconds})
            AND {metric_event_filter}
            """,
            placeholders={
                "date_from": self.date_range_query.date_from_as_hogql(),
                "date_to": self.date_range_query.date_to_as_hogql(),
                "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                "metric_event_filter": metric_event_filter,
            },
        )

    def _build_value_expr(self) -> ast.Expr:
        """
        Extracts the value expression from the metric source configuration.
        """
        assert isinstance(self.metric, ExperimentMeanMetric)
        return get_source_value_expr(self.metric.source)

    def _build_value_aggregation_expr(self) -> ast.Expr:
        """
        Returns the value aggregation expression based on math type.
        """
        assert isinstance(self.metric, ExperimentMeanMetric)

        # Get metric source details
        math_type = getattr(self.metric.source, "math", ExperimentMetricMathType.TOTAL)

        if math_type in [
            ExperimentMetricMathType.UNIQUE_SESSION,
            ExperimentMetricMathType.DAU,
            ExperimentMetricMathType.UNIQUE_GROUP,
        ]:
            # Count distinct values, filtering out null UUIDs and empty strings
            # This matches the old implementation's behavior
            return parse_expr(
                """toFloat(count(distinct
                    multiIf(
                        toTypeName(metric_events.value) = 'UUID' AND reinterpretAsUInt128(metric_events.value) = 0, NULL,
                        toString(metric_events.value) = '', NULL,
                        metric_events.value
                    )
                ))"""
            )
        elif math_type == ExperimentMetricMathType.MIN:
            return parse_expr("min(coalesce(toFloat(metric_events.value), 0))")
        elif math_type == ExperimentMetricMathType.MAX:
            return parse_expr("max(coalesce(toFloat(metric_events.value), 0))")
        elif math_type == ExperimentMetricMathType.AVG:
            return parse_expr("avg(coalesce(toFloat(metric_events.value), 0))")
        elif math_type == ExperimentMetricMathType.HOGQL:
            math_hogql = getattr(self.metric.source, "math_hogql", None)
            if math_hogql is not None:
                aggregation_function, _ = extract_aggregation_and_inner_expr(math_hogql)
                if aggregation_function:
                    return parse_expr(f"{aggregation_function}(coalesce(toFloat(metric_events.value), 0))")
            return parse_expr(f"sum(coalesce(toFloat(metric_events.value), 0))")
        else:
            return parse_expr("sum(coalesce(toFloat(metric_events.value), 0))")

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
                    minIf(timestamp, {exposure_predicate}) AS first_exposure_time,
                    argMinIf(uuid, timestamp, {exposure_predicate}) AS exposure_event_uuid,
                    argMinIf(`$session_id`, timestamp, {exposure_predicate}) AS exposure_session_id
                FROM events
                WHERE {exposure_predicate}
                GROUP BY entity_id
            """,
            placeholders={
                "entity_key": parse_expr(self.entity_key),
                "variant_expr": self._build_variant_expr_for_mean(),
                "exposure_predicate": self._build_exposure_predicate(),
            },
        )
        assert isinstance(exposure_query, ast.SelectQuery)
        return exposure_query

    def _build_variant_expr_for_mean(self) -> ast.Expr:
        """
        Builds the variant selection expression for mean metrics based on multiple variant handling.
        """

        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            return parse_expr(
                "argMinIf({variant_property}, timestamp, {exposure_predicate})",
                placeholders={
                    "variant_property": self._build_variant_property(),
                    "exposure_predicate": self._build_exposure_predicate(),
                },
            )
        else:
            return parse_expr(
                "if(uniqExactIf({variant_property}, {exposure_predicate}) > 1, {multiple_key}, anyIf({variant_property}, {exposure_predicate}))",
                placeholders={
                    "variant_property": self._build_variant_property(),
                    "exposure_predicate": self._build_exposure_predicate(),
                    "multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )

    def _build_funnel_step_columns(self) -> list[ast.Alias]:
        """
        Builds list of step column AST expressions: step_0, step_1, etc.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)
        exposure_criteria = ast.Alias(alias="step_0", expr=self._build_exposure_predicate())
        step_columns = [exposure_criteria]
        for i, funnel_step in enumerate(self.metric.series):
            step_filter = event_or_action_to_filter(self.team, funnel_step)
            step_column = ast.Alias(
                alias=f"step_{i + 1}",
                expr=ast.Call(name="if", args=[step_filter, ast.Constant(value=1), ast.Constant(value=0)]),
            )
            step_columns.append(step_column)

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
