from typing import Union

from posthog.hogql import ast
from posthog.schema import (
    CurrencyCode,
    RevenueTrackingConfig,
    RevenueTrackingEventItem,
)
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.hogql.database.models import (
    StringDatabaseField,
    DateDatabaseField,
    DecimalDatabaseField,
    Table,
    FieldOrTable,
)

DEFAULT_CURRENCY = CurrencyCode.USD


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


# ##############################################
# Revenue from events


# Given an event config and the base config, figure out what the currency should look like
def currency_expression_for_events(config: RevenueTrackingConfig, event_config: RevenueTrackingEventItem) -> ast.Expr:
    # Shouldn't happen but we need it here to make the type checker happy
    if not event_config.revenueCurrencyProperty:
        return ast.Constant(value=(config.baseCurrency or DEFAULT_CURRENCY).value)

    if event_config.revenueCurrencyProperty.property:
        return ast.Call(
            name="upper",
            args=[ast.Field(chain=["events", "properties", event_config.revenueCurrencyProperty.property])],
        )

    currency = event_config.revenueCurrencyProperty.static or config.baseCurrency or DEFAULT_CURRENCY
    return ast.Constant(value=currency.value)


# Given the base config, check that we're looking at the right event and match the right currency to it
def currency_expression_for_all_events(config: RevenueTrackingConfig) -> ast.Expr:
    if not config.events:
        return ast.Constant(value=None)

    exprs: list[ast.Expr] = []
    for event in config.events:
        # Only interested in the comparison expr, not the value expr
        comparison_expr, value_expr = revenue_comparison_and_value_exprs_for_events(
            config, event, do_currency_conversion=False
        )
        exprs.extend(
            [
                comparison_expr,
                currency_expression_for_events(config, event),
            ]
        )

    exprs.append(ast.Constant(value=None))

    return ast.Call(name="multiIf", args=exprs)


# Tuple of (comparison_expr, value_expr) that can be used to:
# - Check whether the event is the one we're looking for
# - Convert the revenue to the base currency if needed
def revenue_comparison_and_value_exprs_for_events(
    config: RevenueTrackingConfig,
    event_config: RevenueTrackingEventItem,
    do_currency_conversion: bool = True,
    amount_expr: ast.Expr | None = None,
) -> tuple[ast.Expr, ast.Expr]:
    if amount_expr is None:
        amount_expr = ast.Field(chain=["events", "properties", event_config.revenueProperty])

    # Check whether the event is the one we're looking for
    comparison_expr = ast.CompareOperation(
        left=ast.Field(chain=["event"]),
        op=ast.CompareOperationOp.Eq,
        right=ast.Constant(value=event_config.eventName),
    )

    # If there's a revenueCurrencyProperty, convert the revenue to the base currency from that property
    # Otherwise, assume we're already in the base currency
    # Also, assume that `base_currency` is USD by default, it'll be empty for most customers
    if event_config.revenueCurrencyProperty and do_currency_conversion:
        value_expr = ast.Call(
            name="if",
            args=[
                ast.Call(name="isNull", args=[currency_expression_for_events(config, event_config)]),
                ast.Call(
                    name="toDecimal",
                    args=[
                        amount_expr,
                        ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                    ],
                ),
                convert_currency_call(
                    amount_expr,
                    currency_expression_for_events(config, event_config),
                    ast.Constant(value=(config.baseCurrency or DEFAULT_CURRENCY).value),
                    ast.Call(name="_toDate", args=[ast.Field(chain=["events", "timestamp"])]),
                ),
            ],
        )
    else:
        value_expr = ast.Call(
            name="toDecimal",
            args=[
                amount_expr,
                ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
            ],
        )

    return (comparison_expr, value_expr)


# This returns an expression that you can add to a `where` clause
# selecting from the `events` table to get the revenue for it
def revenue_expression_for_events(
    config: Union[RevenueTrackingConfig, dict, None],
    do_currency_conversion: bool = True,
    amount_expr: ast.Expr | None = None,
) -> ast.Expr:
    if isinstance(config, dict):
        config = RevenueTrackingConfig.model_validate(config)

    if not config or not config.events:
        return ast.Constant(value=None)

    exprs: list[ast.Expr] = []
    for event in config.events:
        comparison_expr, value_expr = revenue_comparison_and_value_exprs_for_events(
            config,
            event,
            do_currency_conversion=do_currency_conversion,
            amount_expr=amount_expr,
        )
        exprs.extend([comparison_expr, value_expr])

    # Else clause, make sure there's a None at the end
    exprs.append(ast.Constant(value=None))

    return ast.Call(name="multiIf", args=exprs)


# This sums up the revenue from all events in the group
def revenue_sum_expression_for_events(config: Union[RevenueTrackingConfig, dict, None]) -> ast.Expr:
    if isinstance(config, dict):
        config = RevenueTrackingConfig.model_validate(config)

    if not config or not config.events:
        return ast.Constant(value=None)

    exprs: list[ast.Expr] = []
    for event in config.events:
        comparison_expr, value_expr = revenue_comparison_and_value_exprs_for_events(config, event)

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


# This returns an expression that you can add to a `where` clause
# to know if we have a event with valid revenue
def revenue_where_expr_for_events(config: Union[RevenueTrackingConfig, dict, None]) -> ast.Expr:
    if isinstance(config, dict):
        config = RevenueTrackingConfig.model_validate(config)

    if not config or not config.events:
        return ast.Constant(value=False)

    exprs: list[ast.Expr] = []
    for event in config.events:
        # Dont care about conversion, only care about comparison which is independent of conversion
        comparison_expr, _value_expr = revenue_comparison_and_value_exprs_for_events(
            config, event, do_currency_conversion=False
        )
        exprs.append(comparison_expr)

    if len(exprs) == 1:
        return exprs[0]

    return ast.Or(exprs=exprs)
