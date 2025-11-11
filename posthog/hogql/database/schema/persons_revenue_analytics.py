from collections import defaultdict
from typing import cast

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
from posthog.hogql.parser import parse_expr

from products.revenue_analytics.backend.views.schemas import SCHEMAS as VIEW_SCHEMAS

FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id"),
    "person_id": StringDatabaseField(name="person_id"),
    "revenue": DecimalDatabaseField(name="revenue", nullable=False),
    "revenue_last_30_days": DecimalDatabaseField(name="revenue_last_30_days", nullable=False),
}


def join_with_persons_revenue_analytics_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: ast.SelectQuery,
):
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `persons_revenue_analytics`")

    return ast.JoinExpr(
        alias=join_to_add.to_table,
        table=select_from_persons_revenue_analytics_table(context),
        join_type="LEFT JOIN",
        constraint=ast.JoinConstraint(
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[join_to_add.from_table, *join_to_add.lazy_join.from_field]),
                right=ast.Field(chain=[join_to_add.to_table, "person_id"]),
            ),
            constraint_type="ON",
        ),
    )


def select_from_persons_revenue_analytics_table(context: HogQLContext) -> ast.SelectQuery | ast.SelectSetQuery:
    from products.revenue_analytics.backend.views import (
        RevenueAnalyticsBaseView,
        RevenueAnalyticsCustomerView,
        RevenueAnalyticsRevenueItemView,
    )

    if not context.database:
        return ast.SelectQuery.empty(columns=FIELDS)

    # Get all customer/revenue item pairs from the existing views making sure we ignore `all`
    # since the `persons` join is in the child view
    all_views = defaultdict[str, dict[DatabaseSchemaManagedViewTableKind, RevenueAnalyticsBaseView]](defaultdict)
    for view_name in context.database.get_view_names():
        view = cast(SavedQuery | RevenueAnalyticsBaseView, context.database.get_table(view_name))
        prefix = ".".join(view_name.split(".")[:-1])

        customer_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER]
        revenue_item_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM]

        # Might need to convert to RevenueAnalyticsBaseView from a SavedQuery if the FF is enabled
        # Soon we'll be able to remove all of this and handle them all using the `SavedQuery` logic directly
        if view_name.endswith(customer_schema.source_suffix) or view_name.endswith(customer_schema.events_suffix):
            if not isinstance(view, RevenueAnalyticsBaseView):
                view = RevenueAnalyticsCustomerView(
                    id=view.id,
                    query=view.query,
                    name=view.name,
                    fields=view.fields,
                    metadata=view.metadata,
                    # :KLUTCH: None of these properties below are great but it's all we can do to figure this one out for now
                    # We'll be able to come up with a better solution we don't need to support the old managed views anymore
                    prefix=".".join(view.name.split(".")[:-1]),
                    source_id=None,  # Not used so just ignore it
                    event_name=view.name.split(".")[2] if "revenue_analytics.events" in view.name else None,
                )
            all_views[prefix][DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER] = view
        elif view_name.endswith(revenue_item_schema.source_suffix) or view_name.endswith(
            revenue_item_schema.events_suffix
        ):
            if not isinstance(view, RevenueAnalyticsBaseView):
                view = RevenueAnalyticsRevenueItemView(
                    id=view.id,
                    query=view.query,
                    name=view.name,
                    fields=view.fields,
                    metadata=view.metadata,
                    # :KLUTCH: None of these properties below are great but it's all we can do to figure this one out for now
                    # We'll be able to come up with a better solution we don't need to support the old managed views anymore
                    prefix=".".join(view.name.split(".")[:-1]),
                    source_id=None,  # Not used so just ignore it
                    event_name=view.name.split(".")[2] if "revenue_analytics.events" in view.name else None,
                )
            all_views[prefix][DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM] = view

    # Iterate over all possible view pairs and figure out which queries we can add to the set
    queries = []
    for views in all_views.values():
        customer_view = views.get(DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER)
        revenue_item_view = views.get(DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM)

        # Only proceed for those where we have customer/revenue_item pairs
        if customer_view is None or revenue_item_view is None:
            continue

        # If we're working with event views, we can use the person_id field directly
        # Otherwise, we need to join with the persons table by checking whether it exists
        person_id_chain: list[str | int] | None = None
        if customer_view.is_event_view():
            person_id_chain = [RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "customer_id"]
        else:
            persons_lazy_join = customer_view.fields.get("persons")
            if persons_lazy_join is not None and isinstance(persons_lazy_join, ast.LazyJoin):
                person_id_chain = [RevenueAnalyticsCustomerView.get_generic_view_alias(), "persons", "id"]

        if person_id_chain is not None:
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
                    ast.Alias(alias="person_id", expr=ast.Call(name="toUUID", args=[ast.Field(chain=person_id_chain)])),
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
                                    # For POE, we *should* be able to use the events.timestamp field
                                    # but that's not possible given Clickhouse's limitations on what you can do in a subquery
                                    # We should figure out a way to do this in the future
                                    # "toDate(events.timestamp) - INTERVAL {interval} DAY" if is_poe else "today() - INTERVAL {interval} DAY",
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
                group_by=[ast.Field(chain=["person_id"])],
            )

            # If it's a data warehouse view, we need to join with the customer view to get the person_id from it
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


class PersonsRevenueAnalyticsTable(LazyTable):
    fields: dict[str, FieldOrTable] = FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: ast.SelectQuery,
    ):
        return select_from_persons_revenue_analytics_table(context)

    def to_printed_clickhouse(self, context):
        return "persons_revenue_analytics"

    def to_printed_hogql(self):
        return "persons_revenue_analytics"
