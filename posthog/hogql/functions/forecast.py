from posthog.hogql import ast
from posthog.hogql.errors import QueryError

from posthog.dataclasses import frozen

MAX_HORIZON = 1024


def is_forecast_call(name: str) -> bool:
    return name.lower() == "forecast"


@frozen
class ForecastCall:
    input: ast.Expr
    horizon: int

    @property
    def clickhouse_type(self) -> str:
        return "Tuple(p10 Array(Float64), p50 Array(Float64), p90 Array(Float64))"

    @classmethod
    def parse(cls, node: ast.Call) -> "ForecastCall":
        if (
            node.params
            or node.distinct
            or node.filter_expr
            or node.order_by
            or node.within_group
            or len(node.args) != 2
        ):
            raise QueryError("Use forecast(values, horizon), where values is an array of numbers in time order.")
        horizon = node.args[1]
        if (
            not isinstance(horizon, ast.Constant)
            or type(horizon.value) is not int
            or not 1 <= horizon.value <= MAX_HORIZON
        ):
            raise QueryError(f"forecast horizon must be an integer literal between 1 and {MAX_HORIZON}.")
        return cls(input=node.args[0], horizon=horizon.value)
