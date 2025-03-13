from typing import Union

from posthog.hogql import ast
from posthog.schema import CurrencyCode, RevenueTrackingConfig, RevenueTrackingEventItem
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.hogql.database.models import (
    StringDatabaseField,
    DateDatabaseField,
    DecimalDatabaseField,
    Table,
    FieldOrTable,
)


class ExchangeRateTable(Table):
    fields: dict[str, FieldOrTable] = {
        "currency": StringDatabaseField(name="currency", nullable=False),
        "date": DateDatabaseField(name="date", nullable=False),
        "rate": DecimalDatabaseField(name="rate", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "exchange_rate"

    def to_printed_hogql(self):
        return "exchange_rate"


def convert_currency_call(
    amount: ast.Expr, currency_from: ast.Expr, currency_to: ast.Expr, timestamp: ast.Expr | None = None
) -> ast.Expr:
    args = [currency_from, currency_to, amount]
    if timestamp:
        args.append(timestamp)

    return ast.Call(name="convertCurrency", args=args)


def revenue_currency_expression(config: RevenueTrackingConfig) -> ast.Expr:
    exprs = []
    if config.events:
        for event in config.events:
            exprs.extend(
                [
                    ast.CompareOperation(
                        left=ast.Field(chain=["event"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=event.eventName),
                    ),
                    ast.Field(chain=["events", "properties", event.revenueCurrencyProperty])
                    if event.revenueCurrencyProperty
                    else ast.Constant(value=None),
                ]
            )

    if len(exprs) == 0:
        return ast.Constant(value=None)

    # Else clause, make sure there's a None at the end
    exprs.append(ast.Constant(value=None))

    return ast.Call(name="multiIf", args=exprs)


def revenue_comparison_and_value_exprs(
    event: RevenueTrackingEventItem,
    config: RevenueTrackingConfig,
    do_currency_conversion: bool = False,
) -> tuple[ast.Expr, ast.Expr]:
    # Check whether the event is the one we're looking for
    comparison_expr = ast.CompareOperation(
        left=ast.Field(chain=["event"]),
        op=ast.CompareOperationOp.Eq,
        right=ast.Constant(value=event.eventName),
    )

    # If there's a revenueCurrencyProperty, convert the revenue to the base currency from that property
    # Otherwise, assume we're already in the base currency
    # Also, assume that `base_currency` is USD by default, it'll be empty for most customers
    if event.revenueCurrencyProperty and do_currency_conversion:
        value_expr = ast.Call(
            name="if",
            args=[
                ast.Call(
                    name="isNull", args=[ast.Field(chain=["events", "properties", event.revenueCurrencyProperty])]
                ),
                ast.Call(
                    name="toDecimal",
                    args=[
                        ast.Field(chain=["events", "properties", event.revenueProperty]),
                        ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                    ],
                ),
                convert_currency_call(
                    ast.Field(chain=["events", "properties", event.revenueProperty]),
                    ast.Field(chain=["events", "properties", event.revenueCurrencyProperty]),
                    ast.Constant(value=(config.baseCurrency or CurrencyCode.USD).value),
                    ast.Call(name="_toDate", args=[ast.Field(chain=["events", "timestamp"])]),
                ),
            ],
        )
    else:
        value_expr = ast.Call(
            name="toDecimal",
            args=[
                ast.Field(chain=["events", "properties", event.revenueProperty]),
                ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
            ],
        )

    return (comparison_expr, value_expr)


def revenue_expression(
    config: Union[RevenueTrackingConfig, dict, None],
    do_currency_conversion: bool = False,
) -> ast.Expr:
    if isinstance(config, dict):
        config = RevenueTrackingConfig.model_validate(config)

    if not config or not config.events:
        return ast.Constant(value=None)

    exprs: list[ast.Expr] = []
    for event in config.events:
        comparison_expr, value_expr = revenue_comparison_and_value_exprs(event, config, do_currency_conversion)
        exprs.extend([comparison_expr, value_expr])

    # Else clause, make sure there's a None at the end
    exprs.append(ast.Constant(value=None))

    return ast.Call(name="multiIf", args=exprs)


def revenue_sum_expression(
    config: Union[RevenueTrackingConfig, dict, None],
    do_currency_conversion: bool = False,
) -> ast.Expr:
    if isinstance(config, dict):
        config = RevenueTrackingConfig.model_validate(config)

    if not config or not config.events:
        return ast.Constant(value=None)

    exprs: list[ast.Expr] = []
    for event in config.events:
        comparison_expr, value_expr = revenue_comparison_and_value_exprs(event, config, do_currency_conversion)

        exprs.append(
            ast.Call(
                name="sumIf",
                args=[
                    ast.Call(name="ifNull", args=[value_expr, ast.Constant(value=0)]),
                    comparison_expr,
                ],
            )
        )

    if len(exprs) == 1:
        return exprs[0]

    return ast.Call(name="plus", args=exprs)


def revenue_events_where_expr(config: Union[RevenueTrackingConfig, dict, None]) -> ast.Expr:
    if isinstance(config, dict):
        config = RevenueTrackingConfig.model_validate(config)

    if not config or not config.events:
        return ast.Constant(value=False)

    exprs: list[ast.Expr] = []
    for event in config.events:
        # NOTE: Dont care about conversion, only care about comparison which is independent of conversion
        comparison_expr, _value_expr = revenue_comparison_and_value_exprs(event, config, do_currency_conversion=False)
        exprs.append(comparison_expr)

    if len(exprs) == 1:
        return exprs[0]

    return ast.Or(exprs=exprs)
