from copy import deepcopy
from typing import Any, Dict, List
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import FieldOrTable, IntegerDatabaseField, StringDatabaseField, VirtualTable
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver_utils import lookup_field_by_name
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


class EventsSessionSubTable(VirtualTable):
    fields: Dict[str, FieldOrTable] = {
        "$session_id": StringDatabaseField(name="$session_id"),
        "session_duration": IntegerDatabaseField(name="session_duration"),
    }

    def to_printed_clickhouse(self, context):
        return "events"

    def to_printed_hogql(self):
        return "events"


class EventsSessionWhereClauseTraverser(TraversingVisitor):
    compare_operators: List[ast.CompareOperation]
    fields: List[ast.Field]
    query: ast.SelectQuery
    context: HogQLContext

    def __init__(self, query: ast.SelectQuery, context: HogQLContext):
        super().__init__()
        self.compare_operators = []
        self.fields = []
        self.query = query
        self.context = context

        where_with_no_types = CloningVisitor(clear_types=True, clear_locations=True).visit(query.where)
        super().visit(where_with_no_types)

    def visit_field(self, node: ast.Field):
        self.fields.append(node)

    def visit_compare_operation(self, node: ast.CompareOperation):
        self.fields = []
        node_clone = deepcopy(node)

        super().visit(node_clone.left)
        super().visit(node_clone.right)

        for field in self.fields:
            type = None

            if len(field.chain) == 0:
                return

            # If the field contains at least two parts, the first might be a table.
            if len(field.chain) > 1:
                type = self.query.type.tables[field.chain[0]]
                if isinstance(type, ast.TableAliasType):
                    if type.table_type.table.to_printed_clickhouse(self.context) == "events":
                        field.chain.pop(0)
                    else:
                        return
                elif isinstance(type, ast.SelectQueryAliasType):
                    # Ignore for now
                    return

            # Field in scope
            if not type:
                type = lookup_field_by_name(self.query.type, field.chain[0])

            if not type:
                return

        # Only append if we think the underlying fields are accessible
        self.compare_operators.append(node_clone)


def join_with_events_table_session_duration(
    from_table: str,
    to_table: str,
    requested_fields: Dict[str, Any],
    context: HogQLContext,
    node: ast.SelectQuery,
):
    select_query = parse_select(
        """
            select "$session_id", dateDiff('second', min(timestamp), max(timestamp)) as session_duration
            from events
            group by "$session_id"
        """
    )

    compare_operators = EventsSessionWhereClauseTraverser(node, context).compare_operators

    where_clauses = ast.And(
        exprs=[
            *compare_operators,
            ast.CompareOperation(
                left=ast.Field(chain=["$session_id"]), op=ast.CompareOperationOp.NotEq, right=ast.Constant(value="")
            ),
        ]
    )

    select_query.where = where_clauses

    join_expr = ast.JoinExpr(table=select_query)
    join_expr.join_type = "INNER JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[from_table, "$session_id"]),
            right=ast.Field(chain=[to_table, "$session_id"]),
        )
    )

    return join_expr
