from typing import cast, Optional, Self
import posthoganalytics

from posthog.hogql.ast import SelectQuery, And, CompareOperation, CompareOperationOp, Field, JoinExpr
from posthog.hogql.base import Expr
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
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

PERSONS_FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "created_at": DateTimeDatabaseField(name="created_at"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "properties": StringJSONDatabaseField(name="properties"),
    "is_identified": BooleanDatabaseField(name="is_identified"),
    "pdi": LazyJoin(
        from_field=["id"],
        join_table=PersonsPDITable(),
        join_function=persons_pdi_join,
    ),
}


def select_from_persons_table(
    join_or_table: LazyJoinToAdd | LazyTableToAdd,
    context: HogQLContext,
    node: SelectQuery,
    *,
    filter: Optional[Expr] = None,
    is_join: Optional[bool] = None,
):
    from posthog.hogql import ast
    from posthog.hogql.parser import parse_select

    select = cast(
        ast.SelectQuery,
        parse_select(
            """
            SELECT id
            FROM raw_persons
            GROUP BY id
            HAVING equals(argMax(raw_persons.is_deleted, raw_persons.version), 0)
            AND argMax(raw_persons.created_at, raw_persons.version) < now() + interval 1 day
        """
        ),
    )
    select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)

    # This bit optimizes the query by first selecting all IDs for all persons (regardless of whether it's the latest version), and only then aggregating the results
    # We only do this if there are where clauses, _and_ WhereClauseExtractor can extract them
    if node.where:
        inner_select = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT id
            FROM raw_persons
            WHERE
                -- Much faster to pre-select out any deleted persons than doing it in aggregation
                -- This is correct because there are no instances where we'd un-delete a person (ie there are no cases where one version has is_deleted=1 and a later version has is_deleted = 0)
                id NOT IN (select id from raw_persons where is_deleted = 1)
            """
            ),
        )
        extractor = WhereClauseExtractor(context, is_join=is_join)
        extractor.add_local_tables(join_or_table)
        where = extractor.get_inner_where(node)

        if where and inner_select.where:
            inner_select.where = ast.And(exprs=[inner_select.where, where])
            select.where = ast.And(
                exprs=[
                    ast.CompareOperation(
                        left=ast.Field(chain=["id"]), right=inner_select, op=ast.CompareOperationOp.In
                    ),
                    where,  # Technically, adding the where clause here is duplicative, because the outer node filters this out _again_. However, if you're trying to debug the results stay consistent throughout the query (otherwise old versions might pop up again in this subquery)
                ]
            )
    if filter is not None:
        if select.where:
            cast(ast.SelectQuery, cast(ast.CompareOperation, select.where).right).where = ast.And(
                exprs=[select.where, filter]
            )
        else:
            select.where = filter

    for field_name, field_chain in join_or_table.fields_accessed.items():
        # We need to always select the 'id' field for the join constraint. The field name here is likely to
        # be "persons__id" if anything, but just in case, let's avoid duplicates.
        if field_name != "id":
            select.select.append(
                ast.Alias(
                    alias=field_name,
                    expr=ast.Call(name="argMax", args=[ast.Field(chain=field_chain), ast.Field(chain=["version"])]),
                )
            )

    return select


def join_with_persons_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: SelectQuery,
):
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from persons table")
    join_expr = ast.JoinExpr(table=select_from_persons_table(join_to_add, context, node, is_join=True))

    organization: Organization = context.team.organization if context.team else None
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
        "is_deleted": BooleanDatabaseField(name="is_deleted"),
        "version": IntegerDatabaseField(name="version"),
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
        # assume that if the select_from is not persons table we're doing a join
        try:
            is_join = not isinstance(node.select_from.type.table, PersonsTable)
        except AttributeError:
            is_join = False
        if self.filter is not None:
            return select_from_persons_table(
                table_to_add, context, node, filter=clone_expr(self.filter, True), is_join=is_join
            )
        return select_from_persons_table(table_to_add, context, node, is_join=is_join)

    def to_printed_clickhouse(self, context):
        return "person"

    def to_printed_hogql(self):
        return "persons"
