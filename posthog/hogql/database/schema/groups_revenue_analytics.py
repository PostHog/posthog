from collections import defaultdict
from typing import Any, cast

from posthog.schema import DatabaseSchemaManagedViewTableKind

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DecimalDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyJoinToAdd,
    LazyTable,
    LazyTableToAdd,
    SavedQuery,
    StringDatabaseField,
)
from posthog.hogql.errors import ResolutionError

from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION

from products.revenue_analytics.backend.views.schemas import SCHEMAS as VIEW_SCHEMAS

ZERO_DECIMAL = ast.Call(
    name="toDecimal", args=[ast.Constant(value=0), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)]
)

FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id"),
    "group_key": StringDatabaseField(name="group_key"),
    "revenue": DecimalDatabaseField(name="revenue", nullable=False),
    "mrr": DecimalDatabaseField(name="mrr", nullable=False),
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


def _base_view_args_from_saved_query(saved_query: SavedQuery) -> dict[str, Any]:
    return {
        "id": saved_query.id,
        "query": saved_query.query,
        "name": saved_query.name,
        "fields": saved_query.fields,
        "metadata": saved_query.metadata,
        # :KLUDGE: None of these properties below are great but it's all we can do to figure this one out for now
        # We'll be able to come up with a better solution we don't need to support the old managed views anymore
        "prefix": ".".join(saved_query.name.split(".")[:-1]),
        "source_id": None,  # Not used so just ignore it
        "event_name": saved_query.name.split(".")[2] if "revenue_analytics.events" in saved_query.name else None,
    }


def select_from_groups_revenue_analytics_table(context: HogQLContext) -> ast.SelectQuery | ast.SelectSetQuery:
    from products.revenue_analytics.backend.views import (
        RevenueAnalyticsBaseView,
        RevenueAnalyticsCustomerView,
        RevenueAnalyticsMRRView,
        RevenueAnalyticsRevenueItemView,
    )

    if not context.database:
        return ast.SelectQuery.empty(columns=FIELDS)

    customer_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER]
    mrr_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_MRR]
    revenue_item_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM]

    # Get all customer/mrr/revenue item tuples from the existing views making sure we ignore `all`
    # since the `group` join is in the child view
    all_views = defaultdict[str, dict[DatabaseSchemaManagedViewTableKind, RevenueAnalyticsBaseView]](defaultdict)
    for view_name in context.database.get_view_names():
        view = cast(SavedQuery | RevenueAnalyticsBaseView, context.database.get_table(view_name))
        prefix = ".".join(view_name.split(".")[:-1])

        # Might need to convert to RevenueAnalyticsBaseView from a SavedQuery if the FF is enabled
        # Soon we'll be able to remove all of this and handle them all using the `SavedQuery` logic directly
        if view_name.endswith(customer_schema.source_suffix) or view_name.endswith(customer_schema.events_suffix):
            if not isinstance(view, RevenueAnalyticsBaseView):
                view = RevenueAnalyticsCustomerView(**_base_view_args_from_saved_query(view))
            all_views[prefix][DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER] = view
        elif view_name.endswith(revenue_item_schema.source_suffix) or view_name.endswith(
            revenue_item_schema.events_suffix
        ):
            if not isinstance(view, RevenueAnalyticsBaseView):
                view = RevenueAnalyticsRevenueItemView(**_base_view_args_from_saved_query(view))
            all_views[prefix][DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM] = view
        elif view_name.endswith(mrr_schema.source_suffix) or view_name.endswith(mrr_schema.events_suffix):
            if not isinstance(view, RevenueAnalyticsBaseView):
                view = RevenueAnalyticsMRRView(**_base_view_args_from_saved_query(view))
            all_views[prefix][DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_MRR] = view

    # Iterate over all possible view tuples and figure out which queries we can add to the set
    queries = []
    for views in all_views.values():
        customer_view = views.get(DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER)
        mrr_view = views.get(DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_MRR)
        revenue_item_view = views.get(DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM)

        # Only proceed for those where we have the whole tuple
        if customer_view is None or revenue_item_view is None or mrr_view is None:
            continue

        if customer_view.is_event_view():
            # For events, group_keys are on each event (group_0_key through group_4_key)
            # We aggregate by group_key directly from each source, then FULL OUTER JOIN
            # since there's no base entity table to start from
            query = _build_events_query(context, revenue_item_view, mrr_view)
        else:
            # For DW, group_key is a customer-level property (via groups join)
            # We can follow the persons pattern: CustomerView → LEFT JOIN aggregations
            groups_lazy_join = customer_view.fields.get("groups")
            if groups_lazy_join is None or not isinstance(groups_lazy_join, ast.LazyJoin):
                continue
            query = _build_dw_query(context, customer_view, revenue_item_view, mrr_view)

        if query is not None:
            queries.append(query)

    if not queries:
        return ast.SelectQuery.empty(columns=FIELDS)
    elif len(queries) == 1:
        return queries[0]
    else:
        return ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL")


def _build_events_query(
    context: HogQLContext,
    revenue_item_view,
    mrr_view,
) -> ast.SelectQuery:
    """
    Build query for event-based views where group_keys are on each event.

    For events, group_keys (group_0_key through group_4_key) are properties on revenue item events,
    but NOT on MRR events (MRR only has customer_id). This means:
    1. We aggregate revenue by group_key directly from RevenueItemView
    2. We get the customer→group mapping from RevenueItemView (which events have group keys)
    3. We aggregate MRR by customer_id from MRRView
    4. We join MRR to the customer→group mapping to get MRR by group_key
    5. We FULL OUTER JOIN revenue and MRR aggregations by group_key
    """
    from products.revenue_analytics.backend.views import RevenueAnalyticsRevenueItemView

    # For events: expand all 5 group keys using arrayJoin (each event can belong to multiple groups)
    group_key_expr = ast.Call(
        name="arrayJoin",
        args=[
            ast.Array(
                exprs=[
                    ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), f"group_{index}_key"])
                    for index in range(5)
                ]
            )
        ],
    )

    # Get the aggregated revenue by group_key directly from RevenueItemView
    revenue_agg = ast.SelectQuery(
        select=[
            ast.Alias(alias="group_key", expr=group_key_expr),
            ast.Alias(
                alias="revenue",
                expr=ast.Call(
                    name="sum",
                    args=[ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "amount"])],
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

    # MRR view doesn't have group_key fields - it only has customer_id.
    # We need to get the customer→group mapping from RevenueItemView and join it with MRR.
    # First, get distinct (customer_id, group_key) pairs from RevenueItemView
    customer_to_group = ast.SelectQuery(
        select=[
            ast.Alias(
                alias="customer_id",
                expr=ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "customer_id"]),
            ),
            ast.Alias(alias="group_key", expr=group_key_expr),
        ],
        select_from=ast.JoinExpr(
            alias=RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
            table=ast.Field(chain=[revenue_item_view.name]),
        ),
        where=ast.Call(name="notEmpty", args=[ast.Field(chain=["group_key"])]),
        distinct=True,
    )

    # Get MRR aggregated by customer_id from MRRView
    mrr_by_customer = ast.SelectQuery(
        select=[
            ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
            ast.Alias(alias="mrr", expr=ast.Call(name="sum", args=[ast.Field(chain=["mrr"])])),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=[mrr_view.name])),
        group_by=[ast.Field(chain=["customer_id"])],
    )

    # Join MRR to the customer→group mapping to get MRR by group_key
    # A customer's MRR is attributed to all groups they belong to
    mrr_agg = ast.SelectQuery(
        select=[
            ast.Alias(alias="group_key", expr=ast.Field(chain=["customer_to_group", "group_key"])),
            ast.Alias(
                alias="mrr",
                expr=ast.Call(
                    name="sum",
                    args=[ast.Call(name="coalesce", args=[ast.Field(chain=["mrr_by_customer", "mrr"]), ZERO_DECIMAL])],
                ),
            ),
        ],
        select_from=ast.JoinExpr(
            alias="customer_to_group",
            table=customer_to_group,
            next_join=ast.JoinExpr(
                alias="mrr_by_customer",
                table=mrr_by_customer,
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["customer_to_group", "customer_id"]),
                        right=ast.Field(chain=["mrr_by_customer", "customer_id"]),
                    ),
                ),
            ),
        ),
        group_by=[ast.Field(chain=["group_key"])],
    )

    # FULL OUTER JOIN revenue_agg and mrr_agg by group_key.
    # A group with revenue but no MRR still needs to appear (and vice versa).
    return ast.SelectQuery(
        select=[
            ast.Alias(alias="team_id", expr=ast.Constant(value=context.team_id)),
            ast.Alias(
                alias="group_key",
                expr=ast.Call(
                    name="coalesce",
                    args=[
                        ast.Field(chain=["revenue_agg", "group_key"]),
                        ast.Field(chain=["mrr_agg", "group_key"]),
                    ],
                ),
            ),
            ast.Alias(
                alias="revenue",
                expr=ast.Call(name="coalesce", args=[ast.Field(chain=["revenue_agg", "revenue"]), ZERO_DECIMAL]),
            ),
            ast.Alias(
                alias="mrr",
                expr=ast.Call(name="coalesce", args=[ast.Field(chain=["mrr_agg", "mrr"]), ZERO_DECIMAL]),
            ),
        ],
        select_from=ast.JoinExpr(
            alias="revenue_agg",
            table=revenue_agg,
            next_join=ast.JoinExpr(
                alias="mrr_agg",
                table=mrr_agg,
                join_type="FULL OUTER JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["revenue_agg", "group_key"]),
                        right=ast.Field(chain=["mrr_agg", "group_key"]),
                    ),
                ),
            ),
        ),
    )


def _build_dw_query(
    context: HogQLContext,
    customer_view,
    revenue_item_view,
    mrr_view,
) -> ast.SelectQuery:
    """
    Build query for DW views following the persons pattern: CustomerView → LEFT JOIN aggregations.

    For data warehouse views, group_key is a customer-level property (via the groups lazy join),
    similar to how person_id is a customer-level property for persons_revenue_analytics. This means:
    1. We can start from CustomerView as the base entity (like persons does)
    2. LEFT JOIN revenue and MRR aggregations by customer_id
    3. Get group_key from the customer's groups join
    4. GROUP BY group_key since multiple customers can share the same group

    This matches the persons_revenue_analytics pattern and uses LEFT JOINs since CustomerView
    provides the complete set of customers (and thus all possible groups).
    """
    from products.revenue_analytics.backend.views import RevenueAnalyticsCustomerView, RevenueAnalyticsRevenueItemView

    # Get the aggregated revenue by customer_id (not group_key - we aggregate by group at the outer level)
    revenue_agg = ast.SelectQuery(
        select=[
            ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
            ast.Alias(alias="revenue", expr=ast.Call(name="sum", args=[ast.Field(chain=["amount"])])),
        ],
        select_from=ast.JoinExpr(
            alias=RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
            table=ast.Field(chain=[revenue_item_view.name]),
        ),
        group_by=[ast.Field(chain=["customer_id"])],
    )

    # Get the aggregated MRR by customer_id (not group_key - we aggregate by group at the outer level)
    mrr_agg = ast.SelectQuery(
        select=[
            ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
            ast.Alias(alias="mrr", expr=ast.Call(name="sum", args=[ast.Field(chain=["mrr"])])),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=[mrr_view.name])),
        group_by=[ast.Field(chain=["customer_id"])],
    )

    # Starting from the customer table, join with the revenue and mrr aggregated tables.
    # Unlike persons (1:1 customer→person), groups can have many customers (N:1 customer→group),
    # so we need to GROUP BY group_key and SUM the revenue/mrr from all customers in that group.
    group_key_chain: list[str | int] = [RevenueAnalyticsCustomerView.get_generic_view_alias(), "groups", "key"]

    return ast.SelectQuery(
        select=[
            ast.Alias(alias="team_id", expr=ast.Constant(value=context.team_id)),
            ast.Alias(alias="group_key", expr=ast.Field(chain=group_key_chain)),
            ast.Alias(
                alias="revenue",
                expr=ast.Call(
                    name="sum",
                    args=[ast.Call(name="coalesce", args=[ast.Field(chain=["revenue_agg", "revenue"]), ZERO_DECIMAL])],
                ),
            ),
            ast.Alias(
                alias="mrr",
                expr=ast.Call(
                    name="sum",
                    args=[ast.Call(name="coalesce", args=[ast.Field(chain=["mrr_agg", "mrr"]), ZERO_DECIMAL])],
                ),
            ),
        ],
        select_from=ast.JoinExpr(
            alias=RevenueAnalyticsCustomerView.get_generic_view_alias(),
            table=ast.Field(chain=[customer_view.name]),
            next_join=ast.JoinExpr(
                alias="revenue_agg",
                table=revenue_agg,
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]),
                        right=ast.Field(chain=["revenue_agg", "customer_id"]),
                    ),
                ),
                next_join=ast.JoinExpr(
                    alias="mrr_agg",
                    table=mrr_agg,
                    join_type="LEFT JOIN",
                    constraint=ast.JoinConstraint(
                        constraint_type="ON",
                        expr=ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]),
                            right=ast.Field(chain=["mrr_agg", "customer_id"]),
                        ),
                    ),
                ),
            ),
        ),
        group_by=[ast.Field(chain=["group_key"])],
        where=ast.Call(name="notEmpty", args=[ast.Field(chain=["group_key"])]),
    )


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
