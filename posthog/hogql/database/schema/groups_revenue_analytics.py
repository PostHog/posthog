from collections import defaultdict

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DecimalDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyJoinToAdd,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
)
from posthog.hogql.errors import ResolutionError
from posthog.hogql.parser import parse_expr

FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id"),
    "group_key": StringDatabaseField(name="group_key"),
    "revenue": DecimalDatabaseField(name="revenue", nullable=False),
    "revenue_last_30_days": DecimalDatabaseField(name="revenue_last_30_days", nullable=False),
}


def join_with_groups_revenue_analytics_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: ast.SelectQuery,
):
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `groups_revenue_analytics`")

    return ast.JoinExpr(
        alias=join_to_add.to_table,
        table=select_from_groups_revenue_analytics_table(context),
        join_type="LEFT JOIN",
        constraint=ast.JoinConstraint(
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[join_to_add.from_table, *join_to_add.lazy_join.from_field]),
                right=ast.Field(chain=[join_to_add.to_table, "group_key"]),
            ),
            constraint_type="ON",
        ),
    )


def select_from_groups_revenue_analytics_table(context: HogQLContext) -> ast.SelectQuery | ast.SelectSetQuery:
    from products.revenue_analytics.backend.views import (
        RevenueAnalyticsBaseView,
        RevenueAnalyticsCustomerView,
        RevenueAnalyticsRevenueItemView,
    )

    if not context.database:
        return ast.SelectQuery.empty(columns=FIELDS)

    # Get all customer/revenue item pairs from the existing views making sure we ignore `all`
    # since the `group` join is in the child view
    all_views: dict[str, dict[type[RevenueAnalyticsBaseView], RevenueAnalyticsBaseView]] = defaultdict(defaultdict)
    for view_name in context.database.get_view_names():
        view = context.database.get_table(view_name)

        if isinstance(view, RevenueAnalyticsBaseView) and not view.union_all:
            if isinstance(view, RevenueAnalyticsCustomerView):
                all_views[view.prefix][RevenueAnalyticsCustomerView] = view
            elif isinstance(view, RevenueAnalyticsRevenueItemView):
                all_views[view.prefix][RevenueAnalyticsRevenueItemView] = view

    # Iterate over all possible view pairs and figure out which queries we can add to the set
    queries = []
    for views in all_views.values():
        customer_view = views.get(RevenueAnalyticsCustomerView)
        revenue_item_view = views.get(RevenueAnalyticsRevenueItemView)

        # Only proceed for those where we have customer/revenue_item pairs
        if customer_view is None or revenue_item_view is None:
            continue

        # If we're working with event views, we can use the group_key field directly
        # but note that we're getting this from the `RevenueItemView` rather than `Customer`
        # because we don't expose what group a person belongs to, only
        # Otherwise, we need to join with the groups table by checking whether it exists
        # connected to the virtual CustomerView
        group_key_chains: list[ast.Expr] = []
        if customer_view.is_event_view():
            group_key_chains = [
                ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), f"group_{index}_key"])
                for index in range(5)  # [0, 1, 2, 3, 4]
            ]
        else:
            groups_lazy_join = customer_view.fields.get("groups")
            if groups_lazy_join is not None and isinstance(groups_lazy_join, ast.LazyJoin):
                group_key_chains = [
                    ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "groups", "key"])
                ]

        if len(group_key_chains) > 0:
            query = ast.SelectQuery(
                select=[
                    # `team_id` is required to make HogQL happy and edge-case free
                    # by avoiding the need to add an exception when querying this table
                    #
                    # This table is always safe to query "without a `team_id` filter"
                    # because it's simply aggregating data from revenue warehouse views,
                    # and those views are, on their own, safe to query "without a `team_id` filter"
                    # since they're getting data from either the data warehouse (safe) or the events table (safe)
                    ast.Alias(alias="team_id", expr=ast.Constant(value=context.team_id)),
                    # We'll create one row per each possible group key (5 for events, and then only one for joins)
                    ast.Alias(
                        alias="group_key", expr=ast.Call(name="arrayJoin", args=[ast.Array(exprs=group_key_chains)])
                    ),
                    ast.Alias(
                        alias="revenue",
                        expr=ast.Call(
                            name="sum",
                            args=[
                                ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "amount"])
                            ],
                        ),
                    ),
                    ast.Alias(
                        alias="revenue_last_30_days",
                        expr=ast.Call(
                            name="sumIf",
                            args=[
                                ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "amount"]),
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.GtEq,
                                    left=ast.Field(
                                        chain=[
                                            RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                                            "timestamp",
                                        ]
                                    ),
                                    # For GOE, we *should* be able to use the events.timestamp field
                                    # but that's not possible given Clickhouse's limitations on what you can do in a subquery
                                    # We should figure out a way to do this in the future
                                    # "toDate(events.timestamp) - INTERVAL {interval} DAY" if is_goe else "today() - INTERVAL {interval} DAY",
                                    right=parse_expr("today() - INTERVAL 30 DAY"),
                                ),
                            ],
                        ),
                    ),
                ],
                select_from=ast.JoinExpr(
                    alias=RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                    table=ast.Field(chain=[revenue_item_view.name]),
                ),
                group_by=[ast.Field(chain=["group_key"])],
                where=ast.Call(name="notEmpty", args=[ast.Field(chain=["group_key"])]),
            )

            # If it's a data warehouse view, we need to join with the customer view
            if not customer_view.is_event_view():
                query.select_from.next_join = ast.JoinExpr(  # type: ignore
                    alias=RevenueAnalyticsCustomerView.get_generic_view_alias(),
                    table=ast.Field(chain=[customer_view.name]),
                    join_type="INNER JOIN",
                    constraint=ast.JoinConstraint(
                        constraint_type="ON",
                        expr=ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(
                                chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "customer_id"]
                            ),
                            right=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]),
                        ),
                    ),
                )

            queries.append(query)

    if not queries:
        return ast.SelectQuery.empty(columns=FIELDS)
    elif len(queries) == 1:
        return queries[0]
    else:
        return ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL")


class GroupsRevenueAnalyticsTable(LazyTable):
    fields: dict[str, FieldOrTable] = FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: ast.SelectQuery,
    ):
        return select_from_groups_revenue_analytics_table(context)

    def to_printed_clickhouse(self, context):
        return "groups_revenue_analytics"

    def to_printed_hogql(self):
        return "groups_revenue_analytics"
