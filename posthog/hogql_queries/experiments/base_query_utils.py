from typing import Literal, Union
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.models.action.action import Action
from posthog.models.team.team import Team
from posthog.schema import (
    ActionsNode,
    BaseMathType,
    CalendarHeatmapMathType,
    CountPerActorMathType,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    FunnelConversionWindowTimeUnit,
    FunnelMathType,
    PropertyMathType,
)
from posthog.hogql_queries.experiments.hogql_aggregation_utils import extract_aggregation_and_inner_expr


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
