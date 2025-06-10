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


def funnel_steps_to_window_funnel_expr(funnel_metric: ExperimentFunnelMetric) -> ast.Expr:
    """
    Returns the expression for the window funnel. The expression returns 1 if the user completed the whole funnel, 0 if they didn't.
    """

    funnel_steps_str = ", ".join([f"funnel_step = 'step_{i}'" for i, _ in enumerate(funnel_metric.series)])

    num_steps = len(funnel_metric.series)
    if funnel_metric.conversion_window is not None and funnel_metric.conversion_window_unit is not None:
        conversion_window_seconds = conversion_window_to_seconds(
            funnel_metric.conversion_window, funnel_metric.conversion_window_unit
        )
    else:
        # Default to include all events selected, so we just set a large value here (3 years)
        # Events outside the experiment duration will be filtered out by the query runner
        conversion_window_seconds = 3 * 365 * 24 * 60 * 60

    return parse_expr(
        f"windowFunnel({conversion_window_seconds})(toDateTime(timestamp), {funnel_steps_str}) = {num_steps}",
        placeholders={
            "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
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

    # Build step conditions as strings, following the exact pattern from funnel_udf.py
    step_conditions = []
    placeholders = {}
    for i, funnel_step in enumerate(funnel_metric.series):
        filter_expr = event_or_action_to_filter(team, funnel_step)
        step_placeholder = f"step_condition_{i}"
        step_conditions.append(f"multiply({i + 1}, if({{{step_placeholder}}}, 1, 0))")
        placeholders[step_placeholder] = filter_expr

    step_conditions_str = ", ".join(step_conditions)

    # Build the complete UDF expression as a string
    udf_expression = f"""
    toFloat(arraySum(arrayMap(x -> if(x.1 >= {{num_steps_minus_one}}, 1, 0),
        aggregate_funnel_array(
            {{num_steps}},
            {{conversion_window_seconds}},
            'first_touch',
            'ordered',
            array(array('', '')),
            arraySort(t -> t.1, groupArray(tuple(
                toFloat(timestamp),
                uuid,
                '',
                arrayFilter((x) -> x != 0, [{step_conditions_str}])
            )))
        )
    )))
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
