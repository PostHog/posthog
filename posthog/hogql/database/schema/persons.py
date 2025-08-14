from typing import cast, Optional, Self
from posthog.hogql.parser import parse_select
import posthoganalytics

from posthog.hogql.ast import SelectQuery, And, CompareOperation, CompareOperationOp, Field, JoinExpr
from posthog.hogql.base import Expr
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql import ast
from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    LazyTable,
    LazyJoin,
    FieldOrTable,
    LazyTableToAdd,
    LazyJoinToAdd,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)
from posthog.hogql.database.schema.util.where_clause_extractor import WhereClauseExtractor
from posthog.hogql.database.schema.persons_pdi import PersonsPDITable, persons_pdi_join
from posthog.hogql.errors import ResolutionError
from posthog.hogql.visitor import clone_expr
from posthog.models.organization import Organization
from posthog.schema import PersonsArgMaxVersion
from posthog.hogql.database.schema.revenue_analytics import (
    RawPersonsRevenueAnalyticsTable,
    join_with_persons_revenue_analytics_table,
)

from posthog.hogql.visitor import CloningVisitor

PERSONS_FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id", nullable=False),
    "created_at": DateTimeDatabaseField(name="created_at", nullable=False),
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "properties": StringJSONDatabaseField(name="properties", nullable=False),
    "is_identified": BooleanDatabaseField(name="is_identified", nullable=False),
    "pdi": LazyJoin(
        from_field=["id"],
        join_table=PersonsPDITable(),
        join_function=persons_pdi_join,
    ),
    "revenue_analytics": LazyJoin(
        from_field=["id"],
        join_table=RawPersonsRevenueAnalyticsTable(),
        join_function=join_with_persons_revenue_analytics_table,
    ),
}


def select_from_persons_table(
    join_or_table: LazyJoinToAdd | LazyTableToAdd,
    context: HogQLContext,
    node: SelectQuery,
    *,
    filter: Optional[Expr] = None,
):
    version = context.modifiers.personsArgMaxVersion
    if version == PersonsArgMaxVersion.AUTO:
        version = PersonsArgMaxVersion.V1
        # If selecting properties, use the faster v2 query. Otherwise, v1 is faster.
        for field_chain in join_or_table.fields_accessed.values():
            if field_chain[0] == "properties":
                version = PersonsArgMaxVersion.V2
                break

    and_conditions = []

    if filter is not None:
        and_conditions.append(filter)

    # For now, only do this optimization for directly querying the persons table (without joins or as part of a subquery) to avoid knock-on effects to insight queries
    if (
        node.select_from
        and node.select_from.type
        and hasattr(node.select_from.type, "table")
        and node.select_from.type.table
        and isinstance(node.select_from.type.table, PersonsTable)
    ):
        extractor = WhereClauseExtractor(context)
        extractor.add_local_tables(join_or_table)
        where = extractor.get_inner_where(node)
        if where:
            select = argmax_select(
                table_name="raw_persons",
                select_fields=join_or_table.fields_accessed,
                group_fields=["id"],
                argmax_field="version",
                deleted_field="is_deleted",
                timestamp_field_to_clamp="created_at",
            )
            inner_select = cast(
                ast.SelectQuery,
                parse_select(
                    """
                SELECT id FROM raw_persons as where_optimization
                """
                ),
            )

            inner_select.where = where
            select.where = ast.CompareOperation(
                left=ast.Field(chain=["id"]), right=inner_select, op=ast.CompareOperationOp.In
            )
            return select

    if version == PersonsArgMaxVersion.V2:
        select = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT id FROM raw_persons WHERE (id, version) IN (
               SELECT id, max(version) as version
               FROM raw_persons
               GROUP BY id
               HAVING equals(argMax(raw_persons.is_deleted, raw_persons.version), 0)
               AND argMax(raw_persons.created_at, raw_persons.version) < now() + interval 1 day
            )
            """
            ),
        )
        select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
        if filter is not None:
            cast(ast.SelectQuery, cast(ast.CompareOperation, select.where).right).where = filter

        # START order_by/limit optimization.
        # only apply this to queries that directly select from the persons table
        if (
            node.select_from
            and node.select_from.type
            and hasattr(node.select_from.type, "table")
            and node.select_from.type.table
            and isinstance(node.select_from.type.table, PersonsTable)
            and not node.group_by  # TODO: support group_by
        ):
            compare = cast(ast.CompareOperation, select.where)
            right_select = cast(ast.SelectQuery, compare.right)
            if node.order_by:
                right_select.order_by = [CloningVisitor(clear_locations=True).visit(x) for x in node.order_by]
                for order_by in right_select.order_by:
                    order_by.expr = ast.Call(
                        name="argMax", args=[order_by.expr, ast.Field(chain=["raw_persons", "version"])]
                    )

            # Patch: push limit+offset+1 to inner subquery for correct pagination, always set offset=0
            if node.limit:
                node_limit = cast(ast.Constant, node.limit)
                node_offset = cast(ast.Constant, node.offset)
                effective_limit = (
                    (node_limit.value if node.limit else 100) + (node_offset.value if node.offset else 0) + 1
                )
                right_select.limit = ast.Constant(value=effective_limit)
                right_select.offset = ast.Constant(value=0)
                # Do NOT set node.limit/node.offset directly, outer paginator will slice results

        for field_name, field_chain in join_or_table.fields_accessed.items():
            # We need to always select the 'id' field for the join constraint. The field name here is likely to
            # be "persons__id" if anything, but just in case, let's avoid duplicates.
            if field_name != "id":
                select.select.append(
                    ast.Alias(
                        alias=field_name,
                        expr=ast.Field(chain=field_chain),
                    )
                )
    else:
        select = argmax_select(
            table_name="raw_persons",
            select_fields=join_or_table.fields_accessed,
            group_fields=["id"],
            argmax_field="version",
            deleted_field="is_deleted",
            timestamp_field_to_clamp="created_at",
        )
        select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
        if filter is not None:
            if select.where:
                select.where = And(exprs=[select.where, filter])
            else:
                select.where = filter

    if context.modifiers.optimizeJoinedFilters:
        extractor = WhereClauseExtractor(context)
        extractor.add_local_tables(join_or_table)
        where = extractor.get_inner_where(node)
        if where and select.where:
            select.where = And(exprs=[select.where, where])
        elif where:
            select.where = where

    return select


def join_with_persons_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from persons table")
    join_expr = ast.JoinExpr(table=select_from_persons_table(join_to_add, context, node))

    organization: Organization | None = context.team.organization if context.team else None
    if organization is None:
        raise ResolutionError("Organization is required to join with persons table")
    # TODO: @raquelmsmith: Remove flag check and use left join for all once deletes are caught up
    use_inner_join = (
        posthoganalytics.feature_enabled(
            "personless-events-not-supported",
            str(context.team.uuid),
            groups={"organization": str(organization.id)},
            group_properties={
                "organization": {
                    "id": str(organization.id),
                    "created_at": organization.created_at,
                }
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        if organization and context.team
        else False
    )
    if use_inner_join:
        join_expr.join_type = "INNER JOIN"
    else:
        join_expr.join_type = "LEFT JOIN"

    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, "person_id"]),
            right=ast.Field(chain=[join_to_add.to_table, "id"]),
        ),
        constraint_type="ON",
    )
    return join_expr


class RawPersonsTable(Table):
    fields: dict[str, FieldOrTable] = {
        **PERSONS_FIELDS,
        "is_deleted": BooleanDatabaseField(name="is_deleted", nullable=False),
        "version": IntegerDatabaseField(name="version", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "person"

    def to_printed_hogql(self):
        return "raw_persons"


# Persons is a lazy table that allows you to insert a where statement inside of the person subselect
# It pulls any "persons.id in ()" statement inside of the argmax subselect
# This is useful when executing a query for a large team.
class PersonsTable(LazyTable):
    fields: dict[str, FieldOrTable] = PERSONS_FIELDS
    filter: Optional[Expr] = None

    @staticmethod
    def _is_promotable_expr(expr, alias: Optional[str] = None):
        return (
            isinstance(expr, CompareOperation)
            and expr.op == CompareOperationOp.In
            and isinstance(expr.left, Field)
            and expr.left.chain == [alias or "persons", "id"]
        )

    @staticmethod
    def _partition_exprs(exprs, alias: Optional[str] = None):
        not_promotable = []
        promotable = []
        for expr in exprs:
            if PersonsTable._is_promotable_expr(expr, alias):
                # Erase "persons" from the chain before bringing inside
                expr.left = Field(chain=["id"])
                promotable.append(expr)
            else:
                not_promotable.append(expr)

        return promotable, not_promotable

    # If the join has a clause we can bring inside the subselect, create a new table that represents that
    def create_new_table_with_filter(self, join: JoinExpr) -> Self:
        if join.constraint is not None and isinstance(join.constraint.expr, And):
            exprs = cast(And, join.constraint.expr).exprs
            promotable, not_promotable = PersonsTable._partition_exprs(exprs, join.alias)
            if len(promotable) == 0:
                return self
            join.constraint.expr.exprs = not_promotable
            p = self.model_copy()
            if len(promotable) == 1:
                p.filter = promotable[0]
            elif len(promotable) > 1:
                p.filter = And(exprs=promotable)
            return p
        return self

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        if self.filter is not None:
            return select_from_persons_table(table_to_add, context, node, filter=clone_expr(self.filter, True))
        return select_from_persons_table(table_to_add, context, node)

    def to_printed_clickhouse(self, context):
        return "person"

    def to_printed_hogql(self):
        return "persons"
