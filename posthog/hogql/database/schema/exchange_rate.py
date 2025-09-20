from typing import Union

from posthog.schema import RevenueAnalyticsEventItem

from posthog.hogql import ast
from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    DateDatabaseField,
    DecimalDatabaseField,
    FieldOrTable,
    StringDatabaseField,
)

from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.models.team.team import Team


class ExchangeRateTable(DANGEROUS_NoTeamIdCheckTable):
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
def currency_expression_for_events(team: Team, event_config: RevenueAnalyticsEventItem) -> ast.Expr:
    # Shouldn't happen but we need it here to make the type checker happy
    if not event_config.revenueCurrencyProperty:
        return ast.Constant(value=team.base_currency)

    if event_config.revenueCurrencyProperty.property:
        return ast.Call(
            name="upper",
            args=[ast.Field(chain=["events", "properties", event_config.revenueCurrencyProperty.property])],
        )

    if event_config.revenueCurrencyProperty.static:
        return ast.Constant(value=event_config.revenueCurrencyProperty.static.value)

    return ast.Constant(value=team.base_currency)


# Tuple of (comparison_expr, value_expr) that can be used to:
# - Check whether the event is the one we're looking for
# - Convert the revenue to the base currency if needed
def revenue_comparison_and_value_exprs_for_events(
    team: Team,
    event_config: RevenueAnalyticsEventItem,
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
                ast.Call(name="isNull", args=[currency_expression_for_events(team, event_config)]),
                ast.Call(
                    name="toDecimal",
                    args=[
                        amount_expr,
                        ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                    ],
                ),
                convert_currency_call(
                    amount_expr,
                    currency_expression_for_events(team, event_config),
                    ast.Constant(value=team.base_currency),
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


# This sums up the revenue from all events in the group
def revenue_sum_expression_for_events(team: Union[Team, None]) -> ast.Expr:
    if not team or not team.revenue_analytics_config or not team.revenue_analytics_config.events:
        return ast.Constant(value=None)

    exprs: list[ast.Expr] = []
    for event in team.revenue_analytics_config.events:
        comparison_expr, value_expr = revenue_comparison_and_value_exprs_for_events(team, event)

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
def revenue_where_expr_for_events(team: Union[Team, None]) -> ast.Expr:
    if not team or not team.revenue_analytics_config or not team.revenue_analytics_config.events:
        return ast.Constant(value=False)

    exprs: list[ast.Expr] = []
    for event in team.revenue_analytics_config.events:
        # Dont care about conversion, only care about comparison which is independent of conversion
        comparison_expr, _value_expr = revenue_comparison_and_value_exprs_for_events(
            team, event, do_currency_conversion=False
        )
        exprs.append(comparison_expr)

    if len(exprs) == 1:
        return exprs[0]

    return ast.Or(exprs=exprs)
