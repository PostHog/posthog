from copy import deepcopy
from typing import Any, Dict, List, Optional
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    VirtualTable,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver_utils import get_long_table_name, lookup_field_by_name
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


class EventsSessionSubTable(VirtualTable):
    fields: Dict[str, FieldOrTable] = {
        "id": StringDatabaseField(name="$session_id"),
        "duration": IntegerDatabaseField(name="session_duration"),
    }

    def to_printed_clickhouse(self, context):
        return "events"

    def to_printed_hogql(self):
        return "events"


class GetFieldsTraverser(TraversingVisitor):
    fields: List[ast.Field]

    def __init__(self, expr: ast.Expr):
        super().__init__()
        self.fields = []
        super().visit(expr)

    def visit_field(self, node: ast.Field):
        self.fields.append(node)


class CleanTableNameFromChain(CloningVisitor):
    def __init__(self, table_name: str, select_query_type: ast.SelectQueryType):
        super().__init__()
        self.table_name = table_name
        self.select_query_type = select_query_type

    def visit_field(self, node: ast.Field):
        if len(node.chain) > 1 and str(node.chain[0]) in self.select_query_type.tables:
            type = self.select_query_type.tables[str(node.chain[0])]

            name = get_long_table_name(self.select_query_type, type)
            if name == self.table_name:
                node.chain.pop(0)

        return super().visit_field(node)


class WhereClauseExtractor:
    compare_operators: List[ast.Expr]

    def __init__(
        self,
        where_expression: ast.Expr,
        from_table_name: str,
        select_query_type: ast.SelectQueryType,
    ):
        self.table_name = from_table_name
        self.select_query_type = select_query_type
        self.compare_operators = self.run(deepcopy(where_expression))

    def _is_field_on_table(self, field: ast.Field) -> bool:
        if len(field.chain) == 0:
            return False

        type: Optional[ast.Type] = None

        # If the field contains at least two parts, the first might be a table.
        if len(field.chain) > 1 and str(field.chain[0]) in self.select_query_type.tables:
            type = self.select_query_type.tables[str(field.chain[0])]

            name = get_long_table_name(self.select_query_type, type)
            if name != self.table_name:
                return False

        # Field in scope
        if not type:
            type = lookup_field_by_name(self.select_query_type, str(field.chain[0]))

        if not type:
            return False

        # Recursively resolve the rest of the chain until we can point to the deepest node.
        loop_type = type
        chain_to_parse = field.chain[1:]
        while True:
            if isinstance(loop_type, ast.FieldTraverserType):
                chain_to_parse = loop_type.chain + chain_to_parse
                loop_type = loop_type.table_type
                continue
            if len(chain_to_parse) == 0:
                break
            next_chain = chain_to_parse.pop(0)
            loop_type = loop_type.get_child(str(next_chain))
            if loop_type is None:
                return False

        return True

    def run(self, expr: ast.Expr) -> List[ast.Expr]:
        exprs_to_apply: List[ast.Expr] = []

        if isinstance(expr, ast.And):
            for expression in expr.exprs:
                if not isinstance(expression, ast.CompareOperation):
                    continue

                fields = GetFieldsTraverser(expression).fields
                res = [self._is_field_on_table(field) for field in fields]
                if all(res):
                    exprs_to_apply.append(expression)
        elif isinstance(expr, ast.CompareOperation):
            exprs_to_apply.extend(self.run(ast.And(exprs=[expr])))
        elif isinstance(expr, ast.Or):
            pass  # Ignore for now

        # Clone field nodes and remove table name from field chains
        return [
            CleanTableNameFromChain(self.table_name, self.select_query_type).visit(
                CloningVisitor(clear_types=True, clear_locations=True).visit(e)
            )
            for e in exprs_to_apply
        ]


def join_with_events_table_session_duration(
    from_table: str,
    to_table: str,
    requested_fields: Dict[str, Any],
    context: HogQLContext,
    node: ast.SelectQuery,
):
    select_query = parse_select(
        """
            select "$session_id" as id, dateDiff('second', min(timestamp), max(timestamp)) as duration
            from events
                group by id
        """
    )

    if isinstance(select_query, ast.SelectQuery):
        compare_operators = (
            WhereClauseExtractor(node.where, from_table, node.type).compare_operators
            if node.where and node.type
            else []
        )
        select_query.where = ast.And(
            exprs=[
                *compare_operators,
                ast.CompareOperation(
                    left=ast.Field(chain=["id"]),
                    op=ast.CompareOperationOp.NotEq,
                    right=ast.Constant(value=""),
                ),
            ]
        )

    join_expr = ast.JoinExpr(table=select_query)
    join_expr.join_type = "INNER JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[from_table, "$session_id"]),
            right=ast.Field(chain=[to_table, "id"]),
        )
    )

    return join_expr
