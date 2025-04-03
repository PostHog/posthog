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


def event_or_action_to_filter(team: Team, funnel_step: Union[EventsNode, ActionsNode]) -> ast.Expr:
    """
    Returns the filter for a single funnel step.
    """

    if isinstance(funnel_step, ActionsNode):
        try:
            action = Action.objects.get(pk=int(funnel_step.id), team__project_id=team.project_id)
            event_filter = action_to_expr(action)
        except Action.DoesNotExist:
            # If an action doesn't exist, we want to return no events
            event_filter = ast.Constant(value=False)
    else:
        event_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=funnel_step.event),
        )

    if funnel_step.properties:
        event_properties = ast.And(exprs=[property_to_expr(property, team) for property in funnel_step.properties])
        event_filter = ast.And(exprs=[event_filter, event_properties])

    return event_filter


def funnel_steps_to_filter(team: Team, funnel_steps: list[EventsNode | ActionsNode]) -> ast.Expr:
    """
    Returns the OR expression for a list of funnel steps. Will match if any of the funnel steps are true.
    """
    return ast.Or(exprs=[event_or_action_to_filter(team, funnel_step) for funnel_step in funnel_steps])


def funnel_steps_to_window_funnel_expr(funnel_metric: ExperimentFunnelMetric) -> ast.Expr:
    """
    Returns the expression for the window funnel. The expression returns 1 if the user completed the whole funnel, 0 if they didn't.
    """

    def _get_node_name(node: EventsNode | ActionsNode) -> str:
        if isinstance(node, ActionsNode):
            if node.name:
                return node.name
            else:
                raise ValueError(f"Action {node.id} has no name")
        else:
            if node.event:
                return node.event
            else:
                raise ValueError(f"Event {node.event} has no name")

    funnel_steps_str = ", ".join([f"funnel_step = 'step_{i}'" for i, _ in enumerate(funnel_metric.series)])

    # TODO: get conversion time window from funnel config
    num_steps = len(funnel_metric.series)
    conversion_time_window = 6048000000000000
    return parse_expr(
        f"windowFunnel({conversion_time_window})(toDateTime(timestamp), {funnel_steps_str}) = {num_steps}",
        placeholders={
            "conversion_time_window": ast.Constant(value=conversion_time_window),
            "num_steps": ast.Constant(value=num_steps),
        },
    )


def get_funnel_step_level_expr(team: Team, funnel_metric: ExperimentFunnelMetric) -> ast.Expr:
    """
    Returns the expression to get the funnel step level.

    We reuse the filters that are being used to select events/actions in the funnel metric query,
    and pass them into multiIf to get the funnel step level.
    """

    # Contains tuples of (filter: ast.Expr, step_name: ast.Constant)
    filters_and_steps = [
        (event_or_action_to_filter(team, funnel_step), ast.Constant(value=f"step_{i}"))
        for i, funnel_step in enumerate(funnel_metric.series)
    ]
    # Flatten the list of tuples into a list of expressions to pass to multiIf
    multi_if_args = [item for filter_value_pair in filters_and_steps for item in filter_value_pair]

    # Last argument to multiIf is the default value
    multi_if_args.append(ast.Constant(value="step_unknown"))

    return ast.Call(name="multiIf", args=multi_if_args)
