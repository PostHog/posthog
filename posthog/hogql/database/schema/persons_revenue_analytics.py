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
    "person_id": StringDatabaseField(name="person_id"),
    "revenue": DecimalDatabaseField(name="revenue", nullable=False),
    "mrr": DecimalDatabaseField(name="mrr", nullable=False),
}


def _select_from_persons_revenue_analytics_table(context: HogQLContext) -> ast.SelectQuery | ast.SelectSetQuery:
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
    # since the `persons` join is in the child view
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

        # If we're working with event views, we can use the customer's id field directly
        # Otherwise, we need to join with the persons table by checking whether it exists
        person_id_chain: list[str | int] | None = None
        if customer_view.is_event_view():
            person_id_chain = [RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]
        else:
            persons_lazy_join = customer_view.fields.get("persons")
            if persons_lazy_join is not None and isinstance(persons_lazy_join, ast.LazyJoin):
                person_id_chain = [RevenueAnalyticsCustomerView.get_generic_view_alias(), "persons", "id"]

        if person_id_chain is not None:
            # Get the aggregated revenue by customer_id
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

            # Get the aggregated MRR by customer_id
            mrr_agg = ast.SelectQuery(
                select=[
                    ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
                    ast.Alias(alias="mrr", expr=ast.Call(name="sum", args=[ast.Field(chain=["mrr"])])),
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=[mrr_view.name])),
                group_by=[ast.Field(chain=["customer_id"])],
            )

            # Starting from the customer table, join with the revenue and mrr aggregated tables
            # and also map to the underlying `person_id` using the `person_id_chain`
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
                    ast.Alias(alias="person_id", expr=ast.Field(chain=person_id_chain)),
                    ast.Alias(
                        alias="revenue",
                        expr=ast.Call(
                            name="coalesce", args=[ast.Field(chain=["revenue_agg", "revenue"]), ZERO_DECIMAL]
                        ),
                    ),
                    ast.Alias(
                        alias="mrr",
                        expr=ast.Call(name="coalesce", args=[ast.Field(chain=["mrr_agg", "mrr"]), ZERO_DECIMAL]),
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
            )

            queries.append(query)

    if not queries:
        return ast.SelectQuery.empty(columns=FIELDS)
    elif len(queries) == 1:
        return queries[0]
    else:
        return ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL")


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


class PersonsRevenueAnalyticsTable(LazyTable):
    fields: dict[str, FieldOrTable] = FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: ast.SelectQuery,
    ):
        return _select_from_persons_revenue_analytics_table(context)

    def to_printed_clickhouse(self, context):
        return "persons_revenue_analytics"

    def to_printed_hogql(self):
        return "persons_revenue_analytics"


def join_with_persons_revenue_analytics_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: ast.SelectQuery,
):
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `persons_revenue_analytics`")

    return ast.JoinExpr(
        alias=join_to_add.to_table,
        table=_select_from_persons_revenue_analytics_table(context),
        join_type="LEFT JOIN",
        constraint=ast.JoinConstraint(
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Call(
                    name="toString",
                    args=[ast.Field(chain=[join_to_add.from_table, *join_to_add.lazy_join.from_field])],
                ),
                right=ast.Call(name="toString", args=[ast.Field(chain=[join_to_add.to_table, "person_id"])]),
            ),
            constraint_type="ON",
        ),
    )
