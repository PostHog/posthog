from typing import Union
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.schema import (
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
