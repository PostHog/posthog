from datetime import datetime
from typing import Literal, Optional, Union, cast
from zoneinfo import ZoneInfo

from posthog.schema import (
    ActionsNode,
    BaseMathType,
    CalendarHeatmapMathType,
    CountPerActorMathType,
    DateRange,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentEventExposureConfig,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    FunnelConversionWindowTimeUnit,
    FunnelMathType,
    MultipleVariantHandling,
    PropertyMathType,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr

from posthog.hogql_queries.experiments.exposure_query_logic import (
    build_common_exposure_conditions,
    get_exposure_event_and_property,
    get_test_accounts_filter,
    get_variant_selection_expr,
)
from posthog.hogql_queries.experiments.hogql_aggregation_utils import extract_aggregation_and_inner_expr
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Experiment
from posthog.models.action.action import Action
from posthog.models.team.team import Team


def get_data_warehouse_metric_source(
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric, ExperimentRetentionMetric],
) -> ExperimentDataWarehouseNode | None:
    if isinstance(metric, ExperimentMeanMetric) and isinstance(metric.source, ExperimentDataWarehouseNode):
        return metric.source
    elif isinstance(metric, ExperimentRatioMetric):
        # For ratio metrics, return a data warehouse source if either numerator or denominator uses data warehouse
        if isinstance(metric.numerator, ExperimentDataWarehouseNode):
            return metric.numerator
        elif isinstance(metric.denominator, ExperimentDataWarehouseNode):
            return metric.denominator
    return None


def is_continuous(
    math_type: BaseMathType
    | FunnelMathType
    | PropertyMathType
    | CountPerActorMathType
    | ExperimentMetricMathType
    | CalendarHeatmapMathType
    | Literal["unique_group"]
    | Literal["hogql"]
    | None,
) -> bool:
    if math_type in [
        ExperimentMetricMathType.SUM,
        ExperimentMetricMathType.AVG,
        ExperimentMetricMathType.MIN,
        ExperimentMetricMathType.MAX,
    ]:
        return True
    return False


def get_source_value_expr(source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]) -> ast.Expr:
    """
    Returns the expression for extracting values from a given source (EventsNode, ActionsNode, or DataWarehouseNode).
    For count metrics, returns 1. For property-based metrics, extracts the property value.
    """

    if isinstance(source, EventsNode) or isinstance(source, ActionsNode):
        # Check if the source has a math type that indicates continuous values
        if hasattr(source, "math") and is_continuous(source.math):
            # If the metric is a property math type, we need to extract the value from the event property
            metric_property = getattr(source, "math_property", None)
            if metric_property:
                # Use the same property access pattern as trends to get property groups optimization
                return ast.Call(name="toFloat", args=[ast.Field(chain=["properties", metric_property])])
        elif hasattr(source, "math") and source.math == ExperimentMetricMathType.UNIQUE_SESSION:
            return ast.Field(chain=["$session_id"])
        elif hasattr(source, "math") and source.math == ExperimentMetricMathType.DAU:
            return ast.Field(chain=["person_id"])
        elif (
            hasattr(source, "math")
            and source.math == ExperimentMetricMathType.UNIQUE_GROUP
            and source.math_group_type_index
        ):
            return ast.Field(chain=[f"$group_{int(source.math_group_type_index)}"])
        elif (
            hasattr(source, "math")
            and source.math == ExperimentMetricMathType.HOGQL
            and getattr(source, "math_hogql", None) is not None
        ):
            # Extract the inner expression from the HogQL expression
            math_hogql = source.math_hogql
            if math_hogql:
                _, inner_expr = extract_aggregation_and_inner_expr(math_hogql)
                return inner_expr
    elif isinstance(source, ExperimentDataWarehouseNode):
        metric_property = getattr(source, "math_property", None)
        if metric_property:
            return parse_expr(metric_property)

    # Default to count - emit 1 so we can easily sum it up
    return ast.Constant(value=1)


def get_metric_value(
    metric: ExperimentMeanMetric, source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode, None] = None
) -> ast.Expr:
    """
    Backward compatibility wrapper for get_source_value_expr.
    """
    actual_source = source if source is not None else metric.source
    return get_source_value_expr(actual_source)


def event_or_action_to_filter(
    team: Team, entity_node: Union[EventsNode, ActionsNode, ExperimentEventExposureConfig]
) -> ast.Expr:
    """
    Returns the filter for a single entity node.
    """

    if isinstance(entity_node, ActionsNode):
        try:
            action = Action.objects.get(pk=int(entity_node.id), team__project_id=team.project_id)
            event_filter = action_to_expr(action)
        except Action.DoesNotExist:
            # If an action doesn't exist, we want to return no events
            event_filter = ast.Constant(value=False)
    else:
        # If event is None, we want to match all events (no event name filter)
        if entity_node.event is None:
            event_filter = ast.Constant(value=True)
        else:
            event_filter = ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=entity_node.event),
            )

    if entity_node.properties:
        event_properties = ast.And(exprs=[property_to_expr(property, team) for property in entity_node.properties])
        event_filter = ast.And(exprs=[event_filter, event_properties])

    return event_filter


def data_warehouse_node_to_filter(team: Team, node: ExperimentDataWarehouseNode) -> ast.Expr:
    """
    Returns the filter for a data warehouse node, including all properties and fixedProperties.
    """
    # Collect all properties from both properties and fixedProperties
    all_properties = []

    if node.properties:
        all_properties.extend(node.properties)

    if node.fixedProperties:
        all_properties.extend(node.fixedProperties)

    # If no properties, return True (no filtering)
    if not all_properties:
        return ast.Constant(value=True)

    # Use property_to_expr to convert properties to HogQL expressions
    # This follows the same pattern as TrendsQueryBuilder._events_filter()
    return property_to_expr(all_properties, team)


def conversion_window_to_seconds(conversion_window: int, conversion_window_unit: FunnelConversionWindowTimeUnit) -> int:
    multipliers = {
        FunnelConversionWindowTimeUnit.SECOND: 1,
        FunnelConversionWindowTimeUnit.MINUTE: 60,
        FunnelConversionWindowTimeUnit.HOUR: 60 * 60,
        FunnelConversionWindowTimeUnit.DAY: 24 * 60 * 60,
        FunnelConversionWindowTimeUnit.WEEK: 7 * 24 * 60 * 60,
        FunnelConversionWindowTimeUnit.MONTH: 30 * 24 * 60 * 60,
    }

    if conversion_window_unit not in multipliers:
        raise ValueError(f"Unsupported conversion window unit: {conversion_window_unit}")

    return conversion_window * multipliers[conversion_window_unit]


def get_experiment_date_range(
    experiment: Experiment, team: Team, override_end_date: Optional[datetime] = None
) -> DateRange:
    """
    Returns an DateRange object based on the experiment's start and end dates,
    adjusted for the team's timezone if applicable.

    Args:
        experiment: The experiment to get date range for
        team: The team to get timezone settings from
        override_end_date: Optional datetime to use as end date instead of experiment.end_date, used for calculating timeseries results
    """
    if team.timezone:
        tz = ZoneInfo(team.timezone)
        start_date: Optional[datetime] = experiment.start_date.astimezone(tz) if experiment.start_date else None
        if override_end_date:
            end_date: Optional[datetime] = override_end_date.astimezone(tz)
        else:
            end_date = experiment.end_date.astimezone(tz) if experiment.end_date else None
    else:
        start_date = experiment.start_date
        if override_end_date:
            end_date = override_end_date
        else:
            end_date = experiment.end_date

    return DateRange(
        date_from=start_date.isoformat() if start_date else None,
        date_to=end_date.isoformat() if end_date else None,
        explicitDate=True,
    )


def get_source_time_window(
    date_range_query: QueryDateRange,
    left: ast.Expr,
    conversion_window: int | None = None,
    conversion_window_unit=None,
) -> list[ast.CompareOperation]:
    """
    Returns the time window conditions based on conversion window and date range.
    Pure source-based function that doesn't depend on metric object.
    """

    if conversion_window is not None and conversion_window_unit is not None:
        # If conversion window is set, limit events to date_to + window
        date_to = ast.CompareOperation(
            left=left,
            right=ast.Call(
                name="plus",
                args=[
                    ast.Constant(value=date_range_query.date_to()),
                    ast.Call(
                        name="toIntervalSecond",
                        args=[
                            ast.Constant(value=conversion_window_to_seconds(conversion_window, conversion_window_unit)),
                        ],
                    ),
                ],
            ),
            op=ast.CompareOperationOp.Lt,
        )
    else:
        # If no conversion window, just limit to experiment end date
        date_to = ast.CompareOperation(
            op=ast.CompareOperationOp.Lt,
            left=left,
            right=ast.Constant(value=date_range_query.date_to()),
        )

    return [
        # Improve query performance by only fetching events after the experiment started
        ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=left,
            right=ast.Constant(value=date_range_query.date_from()),
        ),
        date_to,
    ]


def get_metric_time_window(
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric],
    date_range_query: QueryDateRange,
    left: ast.Expr,
) -> list[ast.CompareOperation]:
    """
    Backward compatibility wrapper for get_source_time_window.
    """
    return get_source_time_window(date_range_query, left, metric.conversion_window, metric.conversion_window_unit)


def get_exposure_time_window_constraints(
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric, ExperimentRetentionMetric],
    timestamp_field: ast.Field,
    exposure_time_field: ast.Field,
) -> list[ast.CompareOperation]:
    """
    Returns time window constraints for events relative to exposure time.

    This function creates constraints that ensure:
    1. Events occurred after the user was exposed to the experiment
    2. If a conversion window is set, events are within that window after exposure

    Args:
        metric: The experiment metric containing conversion window settings
        timestamp_field: The field representing event timestamp (e.g., metric_events.timestamp)
        exposure_time_field: The field representing first exposure time (e.g., exposures.first_exposure_time)

    Returns:
        List of AST compare operations to be used in WHERE or JOIN ON clauses
    """
    constraints = [
        # Only include events that occurred after the user was exposed to the experiment
        ast.CompareOperation(
            left=timestamp_field,
            right=exposure_time_field,
            op=ast.CompareOperationOp.GtEq,
        )
    ]

    # If conversion window is set, we limit events to that window
    # Otherwise, metric events are cut off by the metric query itself,
    # which limits events to the duration of the experiment.
    if metric.conversion_window and metric.conversion_window_unit:
        # Define conversion window as hours after exposure
        constraints.append(
            ast.CompareOperation(
                left=timestamp_field,
                right=ast.Call(
                    name="plus",
                    args=[
                        exposure_time_field,
                        ast.Call(
                            name="toIntervalSecond",
                            args=[
                                ast.Constant(
                                    value=conversion_window_to_seconds(
                                        metric.conversion_window, metric.conversion_window_unit
                                    )
                                ),
                            ],
                        ),
                    ],
                ),
                op=ast.CompareOperationOp.Lt,
            )
        )

    return constraints


def get_experiment_exposure_query(
    experiment: Experiment,
    feature_flag,
    variants: list[str],
    date_range_query: QueryDateRange,
    team: Team,
    entity_key: str,
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric, ExperimentRetentionMetric],
    multiple_variant_handling: MultipleVariantHandling,
) -> ast.SelectQuery:
    """
    Returns the query for the exposure data. One row per entity. If an entity is exposed to multiple variants,
    we place them in the $multiple variant so we can warn the user and exclude them from the analysis.
    Columns:
        entity_id
        variant
        first_exposure_time
    """
    _, feature_flag_variant_property = get_exposure_event_and_property(
        feature_flag_key=feature_flag.key, exposure_criteria=experiment.exposure_criteria
    )

    # Build common exposure conditions
    exposure_conditions = build_common_exposure_conditions(
        feature_flag_variant_property=feature_flag_variant_property,
        variants=variants,
        date_range_query=date_range_query,
        team=team,
        exposure_criteria=experiment.exposure_criteria,
        feature_flag_key=feature_flag.key,
    )

    exposure_query_select: list[ast.Expr] = [
        ast.Alias(alias="entity_id", expr=ast.Field(chain=[entity_key])),
        ast.Alias(
            alias="variant",
            expr=get_variant_selection_expr(feature_flag_variant_property, multiple_variant_handling),
        ),
        ast.Alias(
            alias="first_exposure_time",
            expr=ast.Call(
                name="min",
                args=[ast.Field(chain=["timestamp"])],
            ),
        ),
        ast.Alias(
            alias="exposure_event_uuid",
            expr=ast.Call(
                name="argMin",
                args=[ast.Field(chain=["uuid"]), ast.Field(chain=["timestamp"])],
            ),
        ),
        ast.Alias(
            alias="exposure_session_id",
            expr=ast.Call(
                name="argMin",
                args=[ast.Field(chain=["$session_id"]), ast.Field(chain=["timestamp"])],
            ),
        ),
    ]
    exposure_query_group_by = [ast.Field(chain=["entity_id"])]
    if data_warehouse_metric_source := get_data_warehouse_metric_source(metric):
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


def get_source_events_query(
    source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode],
    team: Team,
    entity_key: str,
    date_range_query: QueryDateRange,
    conversion_window: int | None = None,
    conversion_window_unit=None,
    experiment=None,
) -> ast.SelectQuery:
    """
    Pure source-based function to build events query.
    Returns the query to get events for a specific source. One row per event, so multiple rows per entity.
    Columns: timestamp, entity_identifier, variant, value
    """
    match source:
        case ExperimentDataWarehouseNode():
            return ast.SelectQuery(
                select=[
                    ast.Alias(
                        alias="timestamp",
                        expr=ast.Field(chain=[source.table_name, source.timestamp_field]),
                    ),
                    ast.Alias(
                        alias="entity_identifier",
                        expr=ast.Field(
                            chain=[
                                source.table_name,
                                *source.data_warehouse_join_key.split("."),
                            ]
                        ),
                    ),
                    ast.Alias(alias="value", expr=get_source_value_expr(source)),
                ],
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=[source.table_name]),
                ),
                where=ast.And(
                    exprs=[
                        *get_source_time_window(
                            date_range_query,
                            left=ast.Field(chain=[source.table_name, source.timestamp_field]),
                            conversion_window=conversion_window,
                            conversion_window_unit=conversion_window_unit,
                        ),
                        data_warehouse_node_to_filter(team, source),
                    ],
                ),
            )

        case EventsNode() | ActionsNode():
            filters = [
                *get_source_time_window(
                    date_range_query,
                    left=ast.Field(chain=["events", "timestamp"]),
                    conversion_window=conversion_window,
                    conversion_window_unit=conversion_window_unit,
                ),
                event_or_action_to_filter(team, source),
            ]
            # Add test accounts filter only if experiment is provided
            if experiment:
                filters.extend(get_test_accounts_filter(team, experiment.exposure_criteria))

            return ast.SelectQuery(
                select=[
                    ast.Field(chain=["events", "timestamp"]),
                    ast.Alias(alias="entity_id", expr=ast.Field(chain=["events", entity_key])),
                    ast.Field(chain=["events", "event"]),
                    ast.Alias(alias="value", expr=get_source_value_expr(source)),
                ],
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=["events"]),
                ),
                where=ast.And(exprs=filters),
            )


def get_metric_events_query(
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric, ExperimentRetentionMetric],
    team: Team,
    entity_key: str,
    experiment: Experiment,
    date_range_query: QueryDateRange,
    source_type: Literal["numerator", "denominator"] | None = None,
) -> ast.SelectQuery:
    """
    Returns the query to get the relevant metric events. One row per event, so multiple rows per entity.
    Columns: timestamp, entity_identifier, variant, value
    For ratio metrics, source_type can be "numerator" or "denominator".
    """

    if isinstance(metric, ExperimentFunnelMetric):
        assert source_type is None
        return _get_metric_events_for_funnel_metric(metric, team, entity_key, experiment, date_range_query)

    if isinstance(metric, ExperimentRetentionMetric):
        raise NotImplementedError("Retention metrics are not yet supported in get_metric_events_query")

    # For ratio metrics, determine which source to use and delegate to source-based function
    if isinstance(metric, ExperimentRatioMetric):
        assert source_type is not None
        source = metric.numerator if source_type == "numerator" else metric.denominator
    else:
        assert source_type is None
        source = metric.source

    return get_source_events_query(
        source,
        team,
        entity_key,
        date_range_query,
        metric.conversion_window,
        metric.conversion_window_unit,
        experiment,
    )


def _get_metric_events_for_funnel_metric(
    metric: ExperimentFunnelMetric,
    team: Team,
    entity_key: str,
    experiment: Experiment,
    date_range_query: QueryDateRange,
) -> ast.SelectQuery:
    """
    Get metric events for a funnel metric.
    """

    # Pre-calculate step conditions to avoid property resolution issues in UDF
    # For each step in the funnel, we create a new column that is 1 if the step is true, 0 otherwise
    step_selects = []
    for i, funnel_step in enumerate(metric.series):
        step_filter = event_or_action_to_filter(team, funnel_step)
        step_selects.append(
            ast.Alias(
                alias=f"step_{i}",
                expr=ast.Call(name="if", args=[step_filter, ast.Constant(value=1), ast.Constant(value=0)]),
            )
        )

    return ast.SelectQuery(
        select=[
            ast.Field(chain=["events", "timestamp"]),
            ast.Alias(alias="entity_id", expr=ast.Field(chain=["events", entity_key])),
            ast.Field(chain=["events", "event"]),
            ast.Field(chain=["events", "uuid"]),
            ast.Field(chain=["events", "properties"]),
            ast.Alias(alias="session_id", expr=ast.Field(chain=["events", "properties", "$session_id"])),
            *step_selects,
        ],
        select_from=ast.JoinExpr(
            table=ast.Field(chain=["events"]),
        ),
        where=ast.And(
            exprs=[
                *get_metric_time_window(metric, date_range_query, left=ast.Field(chain=["events", "timestamp"])),
                *get_test_accounts_filter(team, experiment.exposure_criteria),
                funnel_steps_to_filter(team, metric.series),
            ],
        ),
    )


def get_source_aggregation_expr(
    source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode], table_alias: str = "metric_events"
) -> ast.Expr:
    """
    Returns the aggregation expression for a specific source based on its math type.
    Uses the specified table_alias for field references.
    """
    if isinstance(source, EventsNode) or isinstance(source, ActionsNode):
        math_type = getattr(source, "math", None)
        if math_type in [
            ExperimentMetricMathType.UNIQUE_SESSION,
            ExperimentMetricMathType.DAU,
            ExperimentMetricMathType.UNIQUE_GROUP,
        ]:
            # Clickhouse counts empty values as distinct, so need to explicitly exclude them
            # Also handle the special case of null UUIDs (00000000-0000-0000-0000-000000000000)
            return parse_expr(f"""toFloat(count(distinct
                multiIf(
                    toTypeName({table_alias}.value) = 'UUID' AND reinterpretAsUInt128({table_alias}.value) = 0, NULL,
                    toString({table_alias}.value) = '', NULL,
                    {table_alias}.value
                )
            ))""")
        elif math_type == ExperimentMetricMathType.MIN:
            return parse_expr(f"min(coalesce(toFloat({table_alias}.value), 0))")
        elif math_type == ExperimentMetricMathType.MAX:
            return parse_expr(f"max(coalesce(toFloat({table_alias}.value), 0))")
        elif math_type == ExperimentMetricMathType.AVG:
            return parse_expr(f"avg(coalesce(toFloat({table_alias}.value), 0))")
        elif math_type == ExperimentMetricMathType.HOGQL:
            math_hogql = getattr(source, "math_hogql", None)
            if math_hogql is not None:
                aggregation_function, _ = extract_aggregation_and_inner_expr(math_hogql)
                if aggregation_function:
                    return parse_expr(f"{aggregation_function}(coalesce(toFloat({table_alias}.value), 0))")
            # Default to sum if no aggregation function is found
            return parse_expr(f"sum(coalesce(toFloat({table_alias}.value), 0))")

    # Default aggregation for all other cases (including data warehouse)
    return parse_expr(f"sum(coalesce(toFloat({table_alias}.value), 0))")


def get_metric_aggregation_expr(
    experiment: Experiment,
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric, ExperimentRetentionMetric],
    team: Team,
    source_type: Literal["numerator", "denominator"] | None = None,
) -> ast.Expr:
    """
    Returns the aggregation expression for the metric.
    For ratio metrics, source_type can be "numerator" or "denominator".
    """
    # For ratio metrics, get the appropriate source and delegate to source-based function
    if isinstance(metric, ExperimentRatioMetric):
        source = metric.numerator if source_type == "numerator" else metric.denominator
        return get_source_aggregation_expr(source)

    # For mean metrics, delegate to source-based function
    elif isinstance(metric, ExperimentMeanMetric):
        return get_source_aggregation_expr(metric.source)

    # For funnel metrics, use the existing funnel evaluation logic
    elif isinstance(metric, ExperimentFunnelMetric):
        return funnel_evaluation_expr(team, metric, events_alias="metric_events")

    else:
        raise ValueError(f"Unsupported metric type: {type(metric)}")


def get_winsorized_metric_values_query(
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric], metric_events_query: ast.SelectQuery
) -> ast.SelectQuery:
    """
    Returns the query to winsorize metric values
    One row per entity where the value is winsorized to the lower and upper bounds
    Columns: variant, entity_id, value (winsorized metric values)
    """
    if not isinstance(metric, ExperimentMeanMetric):
        return metric_events_query

    if metric.lower_bound_percentile is not None:
        lower_bound_expr = parse_expr(
            "quantile({level})(value)",
            placeholders={"level": ast.Constant(value=metric.lower_bound_percentile)},
        )
    else:
        lower_bound_expr = parse_expr("min(value)")

    if metric.upper_bound_percentile is not None:
        if getattr(metric, "ignore_zeros", False):
            upper_bound_expr = parse_expr(
                "quantile({level})(if(value != 0, value, null))",
                placeholders={"level": ast.Constant(value=metric.upper_bound_percentile)},
            )
        else:
            upper_bound_expr = parse_expr(
                "quantile({level})(value)",
                placeholders={"level": ast.Constant(value=metric.upper_bound_percentile)},
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


# Funnel utility functions (moved from funnel_query_utils.py to avoid circular imports)


def funnel_steps_to_filter(team: Team, funnel_steps: list[EventsNode | ActionsNode]) -> ast.Expr:
    """
    Returns the OR expression for a list of funnel steps. Will match if any of the funnel steps are true.
    """
    return ast.Or(exprs=[event_or_action_to_filter(team, funnel_step) for funnel_step in funnel_steps])


def funnel_evaluation_expr(
    team: Team, funnel_metric: ExperimentFunnelMetric, events_alias: str, include_exposure: bool = False
) -> ast.Expr:
    """
    Returns an expression using the aggregate_funnel_array UDF to evaluate the funnel.
    Returns the highest step number (0-indexed) that the user reached.

    When events_alias is provided, assumes that step conditions have been pre-calculated
    as step_0, step_1, etc. fields in the aliased table.
    """

    if funnel_metric.conversion_window is not None and funnel_metric.conversion_window_unit is not None:
        conversion_window_seconds = conversion_window_to_seconds(
            funnel_metric.conversion_window, funnel_metric.conversion_window_unit
        )
    else:
        # Default to include all events selected, so we just set a large value here (3 years)
        conversion_window_seconds = 3 * 365 * 24 * 60 * 60

    num_steps = len(funnel_metric.series)
    if include_exposure:
        num_steps += 1

    # Create field references with proper alias support
    timestamp_field = f"{events_alias}.timestamp"
    uuid_field = f"{events_alias}.uuid"

    # When using an alias, assume step conditions are pre-calculated
    step_conditions = [f"{i + 1} * {events_alias}.step_{i}" for i in range(num_steps)]

    step_conditions_str = ", ".join(step_conditions)

    # Determine funnel order type - default to "ordered" for backward compatibility
    funnel_order_type = funnel_metric.funnel_order_type or "ordered"

    # Return tuple of (highest step reached, uuid of that step's event)
    # aggregate_funnel_array returns an array of tuples where:
    # result.1 is the step_reached (0-indexed)
    # result.4 is an array of arrays of UUIDs for each step
    expression = f"""
    arraySort(x -> -x.1,
        arrayMap(
            result -> tuple(
                result.1,
                if(result.1 >= 0 AND length(result.4) > result.1,
                    if(length(arrayElement(result.4, result.1 + 1)) > 0,
                        toString(arrayElement(result.4, result.1 + 1)[1]),
                        ''
                    ),
                    ''
                )
            ),
            aggregate_funnel_array(
                {num_steps},
                {conversion_window_seconds},
                'first_touch',
                '{funnel_order_type}',
                array(array('')),
                [],
                arraySort(t -> t.1, groupArray(tuple(
                    toFloat({timestamp_field}),
                    {uuid_field},
                    array(''),
                    arrayFilter(x -> x != 0, [{step_conditions_str}])
                )))
            )
        )
    )[1]
    """

    return parse_expr(expression)
