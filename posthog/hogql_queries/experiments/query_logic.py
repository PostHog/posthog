from typing import TypeGuard, Union
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.models.team.team import Team
from posthog.schema import (
    ExperimentActionMetricSource,
    ExperimentDataWarehouseMetricSource,
    ExperimentEventMetricSource,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetric,
    ExperimentMetricMathType,
)


def get_data_warehouse_metric_source(
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric],
) -> ExperimentDataWarehouseMetricSource | None:
    if isinstance(metric, ExperimentMeanMetric) and metric.source.type == "data_warehouse":
        return metric.source
    return None


def get_metric_value(metric: ExperimentMeanMetric) -> ast.Expr:
    """
    Returns the expression for the value of the metric. For count metrics, we just emit 1.
    For sum or other math types, we return the metric property (revenue f.ex).
    """

    if metric.math == ExperimentMetricMathType.SUM:
        # If the metric is a property math type, we need to extract the value from the event property
        metric_property = metric.math_property
        if metric_property:
            if metric.source.type == "data_warehouse":
                return parse_expr(metric_property)
            else:
                return parse_expr(
                    "toFloat(JSONExtractRaw(properties, {property}))",
                    placeholders={"property": ast.Constant(value=metric_property)},
                )
    # Else, we default to count
    # We then just emit 1 so we can easily sum it up
    return parse_expr("1")
