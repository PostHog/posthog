from typing import Literal, Union, cast
from zoneinfo import ZoneInfo
import structlog

from posthog.models import Experiment
from posthog.models.team.team import Team
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.models.action.action import Action
from posthog.schema import (
    ActionsNode,
    BaseMathType,
    CalendarHeatmapMathType,
    CountPerActorMathType,
    DateRange,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    FunnelConversionWindowTimeUnit,
    FunnelMathType,
    MultipleVariantHandling,
    PropertyMathType,
)
from posthog.hogql_queries.experiments.exposure_query_logic import (
    get_exposure_event_and_property,
    build_common_exposure_conditions,
    get_variant_selection_expr,
    get_test_accounts_filter,
)

from posthog.hogql_queries.experiments.hogql_aggregation_utils import extract_aggregation_and_inner_expr
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql.errors import InternalHogQLError, ExposedHogQLError
from rest_framework.exceptions import ValidationError

logger = structlog.get_logger(__name__)


def get_data_warehouse_metric_source(
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric],
) -> ExperimentDataWarehouseNode | None:
    if isinstance(metric, ExperimentMeanMetric) and isinstance(metric.source, ExperimentDataWarehouseNode):
        return metric.source
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


def get_metric_value(metric: ExperimentMeanMetric) -> ast.Expr:
    """
    Returns the expression for the value of the metric. For count metrics, we just emit 1.
    For sum or other math types, we return the metric property (revenue f.ex).
    """

    if is_continuous(metric.source.math):
        # If the metric is a property math type, we need to extract the value from the event property
        metric_property = metric.source.math_property
        if metric_property:
            if isinstance(metric.source, ExperimentDataWarehouseNode):
                return parse_expr(metric_property)
            else:
                # Use the same property access pattern as trends to get property groups optimization
                return ast.Call(name="toFloat", args=[ast.Field(chain=["properties", metric_property])])

    elif metric.source.math == ExperimentMetricMathType.UNIQUE_SESSION:
        return ast.Field(chain=["$session_id"])

    elif metric.source.math == ExperimentMetricMathType.HOGQL and metric.source.math_hogql is not None:
        # Extract the inner expression from the HogQL expression
        # This handles cases like "sum(properties.revenue - properties.expense)"
        # where we need to return just the inner part for aggregation
        _, inner_expr = extract_aggregation_and_inner_expr(metric.source.math_hogql)
        return inner_expr

    # Else, we default to count
    # We then just emit 1 so we can easily sum it up
    return ast.Constant(value=1)


def event_or_action_to_filter(team: Team, entity_node: Union[EventsNode, ActionsNode]) -> ast.Expr:
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


def get_experiment_date_range(experiment: Experiment, team: Team) -> DateRange:
    """
    Returns an DateRange object based on the experiment's start and end dates,
    adjusted for the team's timezone if applicable.
    """
    if team.timezone:
        tz = ZoneInfo(team.timezone)
        start_date = experiment.start_date.astimezone(tz) if experiment.start_date else None
        end_date = experiment.end_date.astimezone(tz) if experiment.end_date else None
    else:
        start_date = experiment.start_date
        end_date = experiment.end_date

    return DateRange(
        date_from=start_date.isoformat() if start_date else None,
        date_to=end_date.isoformat() if end_date else None,
        explicitDate=True,
    )


def get_metric_time_window(
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric], date_range_query: QueryDateRange, left: ast.Expr
) -> list[ast.CompareOperation]:
    """
    Returns the time window conditions for the metric based on conversion window and date range.
    """
    if metric.conversion_window is not None and metric.conversion_window_unit is not None:
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
                                    metric.conversion_window, metric.conversion_window_unit
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
            right=ast.Constant(value=date_range_query.date_to()),
        )

    return [
        # Improve query performance by only fetching events after the experiment started
        ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=left,
            right=ast.Constant(value=date_range_query.date_from()),
        ),
        # Ensure the event occurred after the user was exposed to the experiment
        ast.CompareOperation(
            left=left,
            right=ast.Field(chain=["exposure_data", "first_exposure_time"]),
            op=ast.CompareOperationOp.GtEq,
        ),
        time_window_clause,
    ]


def get_experiment_exposure_query(
    experiment: Experiment,
    feature_flag,
    variants: list[str],
    date_range_query: QueryDateRange,
    team: Team,
    entity_key: str,
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric],
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
    event, feature_flag_variant_property = get_exposure_event_and_property(
        feature_flag_key=feature_flag.key, exposure_criteria=experiment.exposure_criteria
    )

    # Build common exposure conditions
    exposure_conditions = build_common_exposure_conditions(
        event=event,
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


def get_metric_events_query(
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric],
    exposure_query: ast.SelectQuery,
    team: Team,
    entity_key: str,
    experiment: Experiment,
    date_range_query: QueryDateRange,
) -> ast.SelectQuery:
    """
    Returns the query to get the relevant metric events. One row per event, so multiple rows per entity.
    Columns: timestamp, entity_identifier, variant, value
    """
    match metric:
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
                            ast.Alias(alias="value", expr=get_metric_value(metric)),
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
                                *get_metric_time_window(
                                    metric,
                                    date_range_query,
                                    left=ast.Field(chain=[metric.source.table_name, metric.source.timestamp_field]),
                                ),
                                data_warehouse_node_to_filter(team, metric.source),
                            ],
                        ),
                    )

                case EventsNode() | ActionsNode() as metric_source:
                    return ast.SelectQuery(
                        select=[
                            ast.Field(chain=["events", "timestamp"]),
                            ast.Alias(alias="entity_id", expr=ast.Field(chain=["events", entity_key])),
                            ast.Field(chain=["exposure_data", "variant"]),
                            ast.Field(chain=["events", "event"]),
                            ast.Alias(alias="value", expr=get_metric_value(metric)),
                        ],
                        select_from=ast.JoinExpr(
                            table=ast.Field(chain=["events"]),
                            next_join=ast.JoinExpr(
                                table=exposure_query,
                                join_type="INNER JOIN",
                                alias="exposure_data",
                                constraint=ast.JoinConstraint(
                                    expr=ast.CompareOperation(
                                        left=ast.Field(chain=["events", entity_key]),
                                        right=ast.Field(chain=["exposure_data", "entity_id"]),
                                        op=ast.CompareOperationOp.Eq,
                                    ),
                                    constraint_type="ON",
                                ),
                            ),
                        ),
                        where=ast.And(
                            exprs=[
                                *get_metric_time_window(
                                    metric, date_range_query, left=ast.Field(chain=["events", "timestamp"])
                                ),
                                event_or_action_to_filter(team, metric_source),
                                *get_test_accounts_filter(team, experiment.exposure_criteria),
                            ],
                        ),
                    )

        case ExperimentFunnelMetric() as metric:
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
                                left=ast.Field(chain=["events", entity_key]),
                                right=ast.Field(chain=["exposure_data", "entity_id"]),
                                op=ast.CompareOperationOp.Eq,
                            ),
                            constraint_type="ON",
                        ),
                    ),
                ),
                where=ast.And(
                    exprs=[
                        *get_metric_time_window(
                            metric, date_range_query, left=ast.Field(chain=["events", "timestamp"])
                        ),
                        *get_test_accounts_filter(team, experiment.exposure_criteria),
                        funnel_steps_to_filter(team, metric.series),
                    ],
                ),
            )

        case _:
            raise ValueError(f"Unsupported metric: {metric}")


def get_metric_aggregation_expr(
    experiment: Experiment, metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric], team: Team
) -> ast.Expr:
    """
    Returns the aggregation expression for the metric.
    """
    try:
        match metric:
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
                    case ExperimentMetricMathType.HOGQL:
                        # For HogQL expressions, extract the aggregation function if present
                        if metric.source.math_hogql is not None:
                            aggregation_function, _ = extract_aggregation_and_inner_expr(metric.source.math_hogql)
                            if aggregation_function:
                                # Use the extracted aggregation function
                                return parse_expr(f"{aggregation_function}(coalesce(toFloat(metric_events.value), 0))")
                        # Default to sum if no aggregation function is found
                        return parse_expr("sum(coalesce(toFloat(metric_events.value), 0))")
                    case _:
                        return parse_expr("sum(coalesce(toFloat(metric_events.value), 0))")
            case ExperimentFunnelMetric():
                return funnel_evaluation_expr(team, metric, events_alias="metric_events")
    except InternalHogQLError as e:
        logger.error(
            "Internal HogQL error in metric aggregation expression",
            experiment_id=experiment.id,
            metric_type=metric.__class__.__name__,
            metric_math=getattr(getattr(metric, "source", None), "math", None),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise ValidationError("Invalid metric configuration for experiment analysis.")
    except ExposedHogQLError:
        raise


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


def funnel_evaluation_expr(team: Team, funnel_metric: ExperimentFunnelMetric, events_alias: str) -> ast.Expr:
    """
    Returns an expression using the aggregate_funnel_array UDF to evaluate the funnel.
    Evaluates to 1 if the user completed the funnel, 0 if they didn't.

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

    # Create field references with proper alias support
    timestamp_field = f"{events_alias}.timestamp"
    uuid_field = f"{events_alias}.uuid"

    # When using an alias, assume step conditions are pre-calculated
    step_conditions = [f"{i + 1} * {events_alias}.step_{i}" for i in range(num_steps)]

    step_conditions_str = ", ".join(step_conditions)

    # Determine funnel order type - default to "ordered" for backward compatibility
    funnel_order_type = funnel_metric.funnel_order_type or "ordered"

    expression = f"""
    if(
        length(
            arrayFilter(result -> result.1 >= {num_steps - 1},
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
        ) > 0,
        1,
        0
    )
    """

    return parse_expr(expression)
