from collections import defaultdict
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


def join_with_persons_revenue_analytics_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: ast.SelectQuery,
):
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from revenue_analytics")

    return ast.JoinExpr(
        alias=join_to_add.to_table,
        table=select_from_persons_revenue_analytics_table(context),
        join_type="LEFT JOIN",
        constraint=ast.JoinConstraint(
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[join_to_add.from_table, "id"]),
                right=ast.Field(chain=[join_to_add.to_table, "person_id"]),
            ),
            constraint_type="ON",
        ),
    )


def select_from_persons_revenue_analytics_table(context: HogQLContext) -> ast.SelectQuery | ast.SelectSetQuery:
    from products.revenue_analytics.backend.views import (
        RevenueAnalyticsBaseView,
        RevenueAnalyticsCustomerView,
        RevenueAnalyticsInvoiceItemView,
    )

    columns = ["person_id", "revenue", "revenue_last_30_days"]

    if not context.database:
        return ast.SelectQuery.empty(columns=columns)

    # Get all customer/invoice_item pairs from the existing views
    all_views: dict[str, dict[type[RevenueAnalyticsBaseView], RevenueAnalyticsBaseView]] = defaultdict(defaultdict)
    for view_name in context.database.get_views():
        view = context.database.get_table(view_name)

        if isinstance(view, RevenueAnalyticsCustomerView):
            all_views[view.prefix][RevenueAnalyticsCustomerView] = view
        elif isinstance(view, RevenueAnalyticsInvoiceItemView):
            all_views[view.prefix][RevenueAnalyticsInvoiceItemView] = view

    # Iterate over all possible view pairs and figure out which queries we can add to the set
    queries = []
    for views in all_views.values():
        customer_view = views.get(RevenueAnalyticsCustomerView)
        invoice_view = views.get(RevenueAnalyticsInvoiceItemView)

        # Only proceed for those where we have customer/invoice_item pairs
        if customer_view is None or invoice_view is None:
            continue

        # If we're working with event views, we can use the person_id field directly
        # Otherwise, we need to join with the persons table by checking whether it exists
        person_id_chain: list[str | int] | None = None
        if customer_view.is_event_view():
            person_id_chain = [RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]
        else:
            persons_lazy_join = customer_view.fields.get("persons")
            if persons_lazy_join is not None and isinstance(persons_lazy_join, ast.LazyJoin):
                person_id_chain = [RevenueAnalyticsCustomerView.get_generic_view_alias(), "persons", "id"]

        if person_id_chain is not None:
            queries.append(
                ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="person_id", expr=ast.Call(name="toUUID", args=[ast.Field(chain=person_id_chain)])
                        ),
                        ast.Alias(
                            alias="revenue",
                            expr=ast.Call(
                                name="sum",
                                args=[
                                    ast.Field(
                                        chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "amount"]
                                    )
                                ],
                            ),
                        ),
                        ast.Alias(
                            alias="revenue_last_30_days",
                            expr=ast.Call(
                                name="sumIf",
                                args=[
                                    ast.Field(
                                        chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "amount"]
                                    ),
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.GtEq,
                                        left=ast.Field(
                                            chain=[
                                                RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                                                "timestamp",
                                            ]
                                        ),
                                        right=parse_expr("today() - INTERVAL 30 DAY"),
                                    ),
                                ],
                            ),
                        ),
                    ],
                    select_from=ast.JoinExpr(
                        alias=RevenueAnalyticsCustomerView.get_generic_view_alias(),
                        table=ast.Field(chain=[customer_view.name]),
                        next_join=ast.JoinExpr(
                            alias=RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                            table=ast.Field(chain=[invoice_view.name]),
                            join_type="LEFT JOIN",
                            constraint=ast.JoinConstraint(
                                constraint_type="ON",
                                expr=ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]),
                                    right=ast.Field(
                                        chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "customer_id"]
                                    ),
                                ),
                            ),
                        ),
                    ),
                    group_by=[ast.Field(chain=["person_id"])],
                )
            )

    if not queries:
        return ast.SelectQuery.empty(columns=columns)
    elif len(queries) == 1:
        return queries[0]
    else:
        return ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL")


class RawPersonsRevenueAnalyticsTable(LazyTable):
    fields: dict[str, FieldOrTable] = {
        "person_id": StringDatabaseField(name="person_id"),
        "revenue": DecimalDatabaseField(name="revenue", nullable=False),
        "revenue_last_30_days": DecimalDatabaseField(name="revenue_last_30_days", nullable=False),
    }

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: ast.SelectQuery,
    ):
        return select_from_persons_revenue_analytics_table(context)

    def to_printed_clickhouse(self, context):
        return "raw_persons_revenue_analytics"

    def to_printed_hogql(self):
        return "raw_persons_revenue_analytics"
