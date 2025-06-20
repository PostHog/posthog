from typing import cast
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.database.models import (
    DecimalDatabaseField,
    StringDatabaseField,
    LazyTable,
    FieldOrTable,
    LazyTableToAdd,
    LazyJoinToAdd,
)
from posthog.hogql.errors import ResolutionError
from products.revenue_analytics.backend.views import (
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsInvoiceItemView,
)

REVENUE_ANALYTICS_FIELDS: dict[str, FieldOrTable] = {
    "distinct_id": StringDatabaseField(name="distinct_id"),
    "revenue": DecimalDatabaseField(name="revenue", nullable=False),
    "revenue_last_30_days": DecimalDatabaseField(name="revenue_last_30_days", nullable=False),
}


def join_with_revenue_analytics_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: ast.SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from revenue_analytics")

    join_expr = ast.JoinExpr(table=select_from_revenue_analytics_table(join_to_add.fields_accessed, context))
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Call(name="toString", args=[ast.Field(chain=[join_to_add.from_table, "distinct_id"])]),
            right=ast.Field(chain=[join_to_add.to_table, "distinct_id"]),
        ),
        constraint_type="ON",
    )
    return join_expr


def select_from_revenue_analytics_table(
    requested_fields: dict[str, list[str | int]],
    context: HogQLContext,
) -> ast.SelectQuery:
    from products.revenue_analytics.backend.utils import (
        revenue_selects_from_database,
        REVENUE_SELECT_OUTPUT_CUSTOMER_KEY,
        REVENUE_SELECT_OUTPUT_INVOICE_ITEM_KEY,
    )

    if not context.database:
        return ast.SelectQuery.empty(columns=list(REVENUE_ANALYTICS_FIELDS.keys()))

    selects = revenue_selects_from_database(context.database)
    customer_selects: list[ast.SelectQuery] = [
        cast(ast.SelectQuery, selects[REVENUE_SELECT_OUTPUT_CUSTOMER_KEY])
        for selects in selects.values()
        if selects[REVENUE_SELECT_OUTPUT_CUSTOMER_KEY] is not None
    ]

    invoice_item_selects: list[ast.SelectQuery] = [
        cast(ast.SelectQuery, selects[REVENUE_SELECT_OUTPUT_INVOICE_ITEM_KEY])
        for selects in selects.values()
        if selects[REVENUE_SELECT_OUTPUT_INVOICE_ITEM_KEY] is not None
    ]

    if not customer_selects or not invoice_item_selects:
        return ast.SelectQuery.empty(columns=list(REVENUE_ANALYTICS_FIELDS.keys()))

    customer_table = ast.SelectSetQuery.create_from_queries(customer_selects, set_operator="UNION ALL")
    invoice_item_table = ast.SelectSetQuery.create_from_queries(invoice_item_selects, set_operator="UNION ALL")

    return ast.SelectQuery(
        select=[
            ast.Alias(
                alias="distinct_id",
                expr=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "distinct_id"]),
            ),
            ast.Alias(
                alias="revenue",
                expr=ast.Call(
                    name="sum",
                    args=[ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "amount"])],
                ),
            ),
            ast.Alias(
                alias="revenue_last_30_days",
                expr=ast.Call(
                    name="sumIf",
                    args=[
                        ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "amount"]),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.GtEq,
                            left=ast.Field(
                                chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"]
                            ),
                            right=parse_expr("today() - INTERVAL 30 DAY"),
                        ),
                    ],
                ),
            ),
        ],
        select_from=ast.JoinExpr(
            alias=RevenueAnalyticsCustomerView.get_generic_view_alias(),
            table=customer_table,
            next_join=ast.JoinExpr(
                alias=RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                table=invoice_item_table,
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=ast.CompareOperation(
                        left=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]),
                        right=ast.Field(
                            chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "customer_id"]
                        ),
                        op=ast.CompareOperationOp.Eq,
                    ),
                ),
            ),
        ),
        group_by=[ast.Field(chain=["distinct_id"])],
    )


class RawRevenueAnalyticsTable(LazyTable):
    fields: dict[str, FieldOrTable] = REVENUE_ANALYTICS_FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: ast.SelectQuery,
    ):
        return select_from_revenue_analytics_table(table_to_add.fields_accessed, context)

    def to_printed_clickhouse(self, context):
        return "raw_revenue_analytics"

    def to_printed_hogql(self):
        return "raw_revenue_analytics"
