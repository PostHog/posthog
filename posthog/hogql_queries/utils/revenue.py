from typing import Union

from posthog.hogql import ast
from posthog.schema import RevenueTrackingConfig


def revenue_expression(config: Union[RevenueTrackingConfig, dict, None]) -> ast.Expr:
    if isinstance(config, dict):
        config = RevenueTrackingConfig.model_validate(config)

    if not config or not config.events:
        return ast.Constant(value=None)

    exprs: list[ast.Expr] = []
    for event in config.events:
        exprs.append(
            ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=event.eventName),
            )
        )
        exprs.append(
            ast.Call(
                name="toFloat",
                args=[ast.Field(chain=["events", "properties", event.revenueProperty])],
            )
        )
    exprs.append(ast.Constant(value=None))

    return ast.Call(name="multiIf", args=exprs)


def revenue_sum_expression(config: Union[RevenueTrackingConfig, dict, None]) -> ast.Expr:
    if isinstance(config, dict):
        config = RevenueTrackingConfig.model_validate(config)

    exprs: list[ast.Expr] = []
    if config:
        for event in config.events:
            exprs.append(
                ast.Call(
                    name="sumIf",
                    args=[
                        ast.Call(
                            name="ifNull",
                            args=[
                                ast.Call(
                                    name="toFloat",
                                    args=[ast.Field(chain=["events", "properties", event.revenueProperty])],
                                ),
                                ast.Constant(value=0),
                            ],
                        ),
                        ast.CompareOperation(
                            left=ast.Field(chain=["event"]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Constant(value=event.eventName),
                        ),
                    ],
                )
            )
    if not exprs:
        return ast.Constant(value=None)
    if len(exprs) == 1:
        return exprs[0]
    return ast.Call(name="plus", args=exprs)


def revenue_events_exprs(config: Union[RevenueTrackingConfig, dict, None]) -> list[ast.Expr]:
    if isinstance(config, dict):
        config = RevenueTrackingConfig.model_validate(config)

    exprs: list[ast.Expr] = []
    if config:
        for event in config.events:
            exprs.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["event"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value=event.eventName),
                )
            )

    return exprs


def revenue_events_expr(config: Union[RevenueTrackingConfig, dict, None]) -> ast.Expr:
    exprs = revenue_events_exprs(config)
    if not exprs:
        return ast.Constant(value=False)
    if len(exprs) == 1:
        return exprs[0]
    return ast.Or(exprs=exprs)
