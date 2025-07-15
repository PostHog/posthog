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
