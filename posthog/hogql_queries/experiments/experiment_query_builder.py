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
from posthog.hogql_queries.experiments.hogql_aggregation_utils import extract_aggregation_and_inner_expr
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team


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

        # Derive which field we should look for the variants
        # TODO: move to it's own function?
        if (
            isinstance(exposure_config, ExperimentEventExposureConfig)
            and exposure_config.event == "$feature_flag_called"
        ):
            self.variant_property = "$feature_flag_response"
        else:
            self.variant_property = f"$feature/{feature_flag_key}"

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
                raise NotImplementedError(f"Only mean and funnel metrics are supported. Got {type(self.metric)}")

    def _build_mean_query(self) -> ast.SelectQuery:
        """
        Builds query for mean metrics (count, sum, avg, etc.)
        """
        assert isinstance(self.metric, ExperimentMeanMetric)

        # Get metric source details
        math_type = getattr(self.metric.source, "math", ExperimentMetricMathType.TOTAL)

        # Calculate conversion window in seconds
        conversion_window_seconds = 0
        if self.metric.conversion_window and self.metric.conversion_window_unit:
            conversion_window_seconds = conversion_window_to_seconds(
                self.metric.conversion_window,
                self.metric.conversion_window_unit,
            )

        # Build conversion window constraint for the join
        if conversion_window_seconds > 0:
            join_time_constraint = """AND metric_events.timestamp >= exposures.first_exposure_time
                    AND metric_events.timestamp < exposures.first_exposure_time + toIntervalSecond({conversion_window_seconds})"""
        else:
            join_time_constraint = "AND metric_events.timestamp >= exposures.first_exposure_time"

        # Build the query with placeholders
        query = parse_select(
            f"""
            WITH exposures AS (
                SELECT
                    {{entity_key}} AS entity_id,
                    {{variant_expr}} AS variant,
                    minIf(timestamp, {{exposure_predicate}}) AS first_exposure_time,
                    argMinIf(uuid, timestamp, {{exposure_predicate}}) AS exposure_event_uuid,
                    argMinIf(`$session_id`, timestamp, {{exposure_predicate}}) AS exposure_session_id
                FROM events
                WHERE {{exposure_predicate}}
                GROUP BY entity_id
            ),

            metric_events AS (
                SELECT
                    {{entity_key}} AS entity_id,
                    timestamp,
                    {{value_expr}} AS value
                FROM events
                WHERE {{metric_predicate}}
            ),

            entity_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    {{value_agg}} AS value
                FROM exposures
                LEFT JOIN metric_events ON exposures.entity_id = metric_events.entity_id
                    {join_time_constraint}
                GROUP BY exposures.entity_id, exposures.variant
            )

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                sum(entity_metrics.value) AS total_sum,
                sum(power(entity_metrics.value, 2)) AS total_sum_of_squares
            FROM entity_metrics
            GROUP BY entity_metrics.variant
            """,
            placeholders={
                "entity_key": parse_expr(self.entity_key),
                "variant_expr": self._build_variant_expr(),
                "exposure_predicate": self._build_exposure_predicate(),
                "metric_predicate": self._build_metric_predicate(),
                "value_expr": self._build_value_expr(),
                "value_agg": self._build_value_aggregation_expr(math_type),
                "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    def _build_test_accounts_filter(self) -> ast.Expr:
        if (
            self.filter_test_accounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            return ast.And(exprs=[property_to_expr(property, self.team) for property in self.team.test_account_filters])
        return ast.Constant(value=True)

    def _build_variant_expr(self) -> ast.Expr:
        """
        Builds the variant selection expression based on multiple variant handling.
        """

        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            return parse_expr(
                "argMinIf({variant_property}, timestamp, {exposure_predicate})",
                placeholders={
                    "variant_property": ast.Field(chain=["properties", self.variant_property]),
                    "exposure_predicate": self._build_exposure_predicate(),
                },
            )
        else:
            return parse_expr(
                "if(uniqExactIf({variant_property}, {exposure_predicate}) > 1, {multiple_key}, anyIf({variant_property}, {exposure_predicate}))",
                placeholders={
                    "variant_property": ast.Field(chain=["properties", self.variant_property]),
                    "exposure_predicate": self._build_exposure_predicate(),
                    "multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )

    def _build_exposure_predicate(self) -> ast.Expr:
        """
        Builds the exposure predicate as an AST expression.
        """
        event_predicate = event_or_action_to_filter(self.team, self.exposure_config)

        if (
            isinstance(self.exposure_config, ExperimentEventExposureConfig)
            and self.exposure_config.event == "$feature_flag_called"
        ):
            # $feature_flag_called events are special. We need to check that the property
            # $feature_flag matches the flag
            # TODO: Is there a nicer way to express this logic?
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

        return parse_expr(
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
                "variant_property": ast.Field(chain=["properties", self.variant_property]),
                "variants": ast.Constant(value=self.variants),
                "test_accounts_filter": self._build_test_accounts_filter(),
            },
        )

    def _build_metric_predicate(self) -> ast.Expr:
        """
        Builds the metric predicate as an AST expression.
        """

        assert isinstance(self.metric, ExperimentMeanMetric)

        # TODO: Implement support for DatawarehouseNode
        assert isinstance(self.metric.source, EventsNode | ActionsNode)

        metric_event_filter = event_or_action_to_filter(self.team, self.metric.source)

        # Build conversion window constraint
        if self.metric.conversion_window and self.metric.conversion_window_unit:
            conversion_window_seconds = conversion_window_to_seconds(
                self.metric.conversion_window,
                self.metric.conversion_window_unit,
            )
        else:
            conversion_window_seconds = 0

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
        Builds the value expression for metric events based on math type.
        """
        assert isinstance(self.metric, ExperimentMeanMetric)
        # TODO: refactor this
        return get_source_value_expr(self.metric.source)

    def _build_value_aggregation_expr(self, math_type: ExperimentMetricMathType) -> ast.Expr:
        """
        Returns the value aggregation expression based on math type.
        """
        assert isinstance(self.metric, ExperimentMeanMetric)

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
            return parse_expr("coalesce(min(toFloat(metric_events.value)), 0.0)")
        elif math_type == ExperimentMetricMathType.MAX:
            return parse_expr("coalesce(max(toFloat(metric_events.value)), 0.0)")
        elif math_type == ExperimentMetricMathType.AVG:
            return parse_expr("coalesce(avg(toFloat(metric_events.value)), 0.0)")
        elif math_type == ExperimentMetricMathType.HOGQL:
            math_hogql = getattr(self.metric.source, "math_hogql", None)
            if math_hogql is not None:
                aggregation_function, _ = extract_aggregation_and_inner_expr(math_hogql)
                if aggregation_function:
                    return parse_expr(f"{aggregation_function}(coalesce(toFloat(metric_events.value), 0))")
            # Default to sum if no aggregation function is found
            return parse_expr(f"sum(coalesce(toFloat(metric_events.value), 0))")
        else:
            # Default: SUM or TOTAL
            return parse_expr("coalesce(sum(toFloat(metric_events.value)), 0.0)")

    def _build_funnel_query(self) -> ast.SelectQuery:
        """
        Builds query for funnel metrics.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)

        num_steps = len(self.metric.series)

        # Calculate conversion window in seconds
        conversion_window_seconds = 0
        if self.metric.conversion_window and self.metric.conversion_window_unit:
            conversion_window_seconds = conversion_window_to_seconds(
                self.metric.conversion_window,
                self.metric.conversion_window_unit,
            )

        # Build conversion window constraint for the join
        if conversion_window_seconds > 0:
            join_time_constraint = """AND metric_events.timestamp >= exposures.first_exposure_time
                    AND metric_events.timestamp < exposures.first_exposure_time + toIntervalSecond({conversion_window_seconds})"""
        else:
            join_time_constraint = "AND metric_events.timestamp >= exposures.first_exposure_time"

        # Build the base query using parse_select
        query = parse_select(
            f"""
            WITH exposures AS (
                SELECT
                    {{entity_key}} AS entity_id,
                    {{variant_expr}} AS variant,
                    minIf(timestamp, {{exposure_predicate}}) AS first_exposure_time,
                    argMinIf(uuid, timestamp, {{exposure_predicate}}) AS exposure_event_uuid,
                    argMinIf(`$session_id`, timestamp, {{exposure_predicate}}) AS exposure_session_id
                FROM events
                WHERE {{exposure_predicate}}
                GROUP BY entity_id
            ),

            metric_events AS (
                SELECT
                    {{entity_key}} AS entity_id,
                    timestamp,
                    uuid,
                    properties.$session_id AS session_id
                FROM events
                WHERE {{funnel_steps_filter}}
            ),

            entity_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    any(exposures.exposure_event_uuid) AS exposure_event_uuid,
                    any(exposures.exposure_session_id) AS exposure_session_id,
                    {{funnel_aggregation}} AS value,
                    {{uuid_to_session_map}} AS uuid_to_session
                FROM exposures
                LEFT JOIN metric_events ON exposures.entity_id = metric_events.entity_id
                    {join_time_constraint}
                GROUP BY exposures.entity_id, exposures.variant
            )

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                countIf(entity_metrics.value.1 = {{num_steps_minus_1}}) AS total_sum,
                countIf(entity_metrics.value.1 = {{num_steps_minus_1}}) AS total_sum_of_squares
            FROM entity_metrics
            GROUP BY entity_metrics.variant
            """,
            placeholders={
                "entity_key": parse_expr(self.entity_key),
                "variant_expr": self._build_variant_expr(),
                "exposure_predicate": self._build_exposure_predicate(),
                "funnel_steps_filter": self._build_funnel_steps_filter(),
                "funnel_aggregation": self._build_funnel_aggregation_expr(),
                "num_steps_minus_1": ast.Constant(value=num_steps - 1),
                "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                "uuid_to_session_map": self._build_uuid_to_session_map(),
            },
        )

        assert isinstance(query, ast.SelectQuery)

        # Now manually inject step columns into the metric_events CTE
        # Find the metric_events CTE in the query
        if query.ctes and "metric_events" in query.ctes:
            metric_events_cte = query.ctes["metric_events"]
            if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
                # Add step columns to the SELECT
                step_columns = self._build_funnel_step_columns()
                metric_events_cte.expr.select.extend(step_columns)

        return query

    def _build_funnel_step_columns(self) -> list[ast.Alias]:
        """
        Builds list of step column AST expressions: step_0, step_1, etc.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)

        step_columns = []
        for i, funnel_step in enumerate(self.metric.series):
            step_filter = event_or_action_to_filter(self.team, funnel_step)
            step_column = ast.Alias(
                alias=f"step_{i+1}",
                expr=ast.Call(name="if", args=[step_filter, ast.Constant(value=1), ast.Constant(value=0)]),
            )
            step_columns.append(step_column)

        return step_columns

    def _build_funnel_steps_filter(self) -> ast.Expr:
        """
        Returns the OR expression for all funnel steps (matches ANY step).
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)
        return funnel_steps_to_filter(self.team, self.metric.series)

    def _build_funnel_aggregation_expr(self) -> ast.Expr:
        """
        Returns the funnel evaluation expression using aggregate_funnel_array.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)
        return funnel_evaluation_expr(self.team, self.metric, events_alias="metric_events")

    def _build_uuid_to_session_map(self) -> ast.Expr:
        """
        Creates a map from event UUID to session ID for funnel metrics.
        """
        return parse_expr(
            "mapFromArrays(groupArray(coalesce(toString(metric_events.uuid), '')), groupArray(coalesce(toString(metric_events.session_id), '')))"
        )
