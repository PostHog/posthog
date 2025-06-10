from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.models.team.team import Team
from posthog.hogql_queries.experiments.base_query_utils import (
    conversion_window_to_seconds,
    event_or_action_to_filter,
)
from posthog.schema import (
    ActionsNode,
    EventsNode,
    ExperimentFunnelMetric,
)


def funnel_steps_to_filter(team: Team, funnel_steps: list[EventsNode | ActionsNode]) -> ast.Expr:
    """
    Returns the OR expression for a list of funnel steps. Will match if any of the funnel steps are true.
    """
    return ast.Or(exprs=[event_or_action_to_filter(team, funnel_step) for funnel_step in funnel_steps])


def funnel_steps_to_aggregate_funnel_array_expr(team: Team, funnel_metric: ExperimentFunnelMetric) -> ast.Expr:
    """
    Returns the expression using aggregate_funnel_array UDF for funnel analysis.
    This handles cases with duplicate events that windowFunnel cannot process.
    """
    num_steps = len(funnel_metric.series)

    if funnel_metric.conversion_window is not None and funnel_metric.conversion_window_unit is not None:
        conversion_window_seconds = conversion_window_to_seconds(
            funnel_metric.conversion_window, funnel_metric.conversion_window_unit
        )
    else:
        # Default to include all events selected, so we just set a large value here (3 years)
        conversion_window_seconds = 3 * 365 * 24 * 60 * 60

    # Build step conditions using multiply pattern
    step_conditions = []
    placeholders = {}
    for i, funnel_step in enumerate(funnel_metric.series):
        filter_expr = event_or_action_to_filter(team, funnel_step)
        step_placeholder = f"step_condition_{i}"
        step_conditions.append(f"multiply({i + 1}, if({{{step_placeholder}}}, 1, 0))")
        placeholders[step_placeholder] = filter_expr

    step_conditions_str = ", ".join(step_conditions)

    udf_expression = f"""
    if(
        length(
            arrayFilter(result -> result.1 >= {{num_steps_minus_one}},
                aggregate_funnel_array(
                    {{num_steps}},
                    {{conversion_window_seconds}},
                    'first_touch',
                    'ordered',
                    array(array('')),
                    arraySort(t -> t.1, groupArray(tuple(
                        toFloat(timestamp),
                        uuid,
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

    # Add the numeric placeholders
    placeholders.update(
        {
            "num_steps": ast.Constant(value=num_steps),
            "num_steps_minus_one": ast.Constant(value=num_steps - 1),
            "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
        }
    )

    return parse_expr(udf_expression, placeholders=placeholders)
