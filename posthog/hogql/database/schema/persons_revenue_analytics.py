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
    SavedQuery,
    StringDatabaseField,
)
from posthog.hogql.errors import ResolutionError

from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION

from products.revenue_analytics.backend.views import (
    CUSTOMER_ALIAS,
    MRR_ALIAS,
    REVENUE_ITEM_ALIAS,
    RevenueAnalyticsViewKind,
    is_event_view,
    is_revenue_analytics_view,
)
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
    if not context.database:
        return ast.SelectQuery.empty(columns=FIELDS)

    customer_schema = VIEW_SCHEMAS[CUSTOMER_ALIAS]
    mrr_schema = VIEW_SCHEMAS[MRR_ALIAS]
    revenue_item_schema = VIEW_SCHEMAS[REVENUE_ITEM_ALIAS]

    # Get all customer/mrr/revenue item tuples from the existing views making sure we ignore `all`
    # since the `persons` join is in the child view
    all_views = defaultdict[str, dict[RevenueAnalyticsViewKind, SavedQuery]](defaultdict)
    for view_name in context.database.get_view_names():
        view = context.database.get_table(view_name)
        if not isinstance(view, SavedQuery) or not is_revenue_analytics_view(view):
            continue

        prefix = ".".join(view_name.split(".")[:-1])

        if view_name.endswith(customer_schema.source_suffix) or view_name.endswith(customer_schema.events_suffix):
            all_views[prefix][CUSTOMER_ALIAS] = view
        elif view_name.endswith(revenue_item_schema.source_suffix) or view_name.endswith(
            revenue_item_schema.events_suffix
        ):
            all_views[prefix][REVENUE_ITEM_ALIAS] = view
        elif view_name.endswith(mrr_schema.source_suffix) or view_name.endswith(mrr_schema.events_suffix):
            all_views[prefix][MRR_ALIAS] = view

    # Iterate over all possible view tuples and figure out which queries we can add to the set
    queries = []
    for views in all_views.values():
        customer_view = views.get(CUSTOMER_ALIAS)
        mrr_view = views.get(MRR_ALIAS)
        revenue_item_view = views.get(REVENUE_ITEM_ALIAS)

        # Only proceed for those where we have the whole tuple
        if customer_view is None or revenue_item_view is None or mrr_view is None:
            continue

        # If we're working with event views, we can use the customer's id field directly
        # Otherwise, we need to join with the persons table by checking whether it exists
        person_id_chain: list[str | int] | None = None
        if is_event_view(customer_view):
            person_id_chain = [CUSTOMER_ALIAS, "id"]
        else:
            persons_lazy_join = customer_view.fields.get("persons")
            if persons_lazy_join is not None and isinstance(persons_lazy_join, ast.LazyJoin):
                person_id_chain = [CUSTOMER_ALIAS, "persons", "id"]

        if person_id_chain is not None:
            # Get the aggregated revenue by customer_id
            revenue_agg = ast.SelectQuery(
                select=[
                    ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
                    ast.Alias(alias="revenue", expr=ast.Call(name="sum", args=[ast.Field(chain=["amount"])])),
                ],
                select_from=ast.JoinExpr(
                    alias=REVENUE_ITEM_ALIAS,
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
                    alias=CUSTOMER_ALIAS,
                    table=ast.Field(chain=[customer_view.name]),
                    next_join=ast.JoinExpr(
                        alias="revenue_agg",
                        table=revenue_agg,
                        join_type="LEFT JOIN",
                        constraint=ast.JoinConstraint(
                            constraint_type="ON",
                            expr=ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=[CUSTOMER_ALIAS, "id"]),
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
                                    left=ast.Field(chain=[CUSTOMER_ALIAS, "id"]),
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
