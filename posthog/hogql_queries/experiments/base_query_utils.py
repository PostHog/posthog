from typing import Union
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.models.action.action import Action
from posthog.models.team.team import Team
from posthog.schema import (
    ActionsNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
)


def get_data_warehouse_metric_source(
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric],
) -> ExperimentDataWarehouseNode | None:
    if isinstance(metric, ExperimentMeanMetric) and isinstance(metric.source, ExperimentDataWarehouseNode):
        return metric.source
    return None


def get_metric_value(metric: ExperimentMeanMetric) -> ast.Expr:
    """
    Returns the expression for the value of the metric. For count metrics, we just emit 1.
    For sum or other math types, we return the metric property (revenue f.ex).
    """

    if metric.source.math == ExperimentMetricMathType.SUM:
        # If the metric is a property math type, we need to extract the value from the event property
        metric_property = metric.source.math_property
        if metric_property:
            if isinstance(metric.source, ExperimentDataWarehouseNode):
                return parse_expr(metric_property)
            else:
                return parse_expr(
                    "toFloat(JSONExtractRaw(properties, {property}))",
                    placeholders={"property": ast.Constant(value=metric_property)},
                )
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
        event_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=entity_node.event),
        )

    if entity_node.properties:
        event_properties = ast.And(exprs=[property_to_expr(property, team) for property in entity_node.properties])
        event_filter = ast.And(exprs=[event_filter, event_properties])

    return event_filter
