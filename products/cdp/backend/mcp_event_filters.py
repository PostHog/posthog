from rest_framework.exceptions import PermissionDenied

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.resolver import Resolver
from posthog.hogql.restricted_properties import (
    RESTRICTABLE_JSON_BLOB_COLUMNS,
    mirrored_property_for_column,
    native_property_path_overlaps_restriction,
    restricted_property_keys_for_table_type,
)
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.models import Team, User


class MCPEventFilterAccessValidator(TraversingVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context

    @classmethod
    def validate(cls, expression: ast.Expr, *, team: Team, user: User) -> None:
        query = ast.SelectQuery(
            select=[ast.Constant(value=1)],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=expression,
            limit=ast.Constant(value=1),
        )
        _, context = HogQLQueryExecutor(query=query, team=team, user=user).generate_clickhouse_sql()
        if not context.restricted_properties:
            return
        # CDP evaluates raw globals, so SQL's masking cannot protect a queued filter's match decision.
        resolved = Resolver(context=context, dialect="hogql").visit(clone_expr(query, True))
        cls(context).visit(resolved)

    def visit_field(self, node: ast.Field) -> None:
        field_type = node.type
        if isinstance(field_type, ast.PropertyType) and field_type.chain:
            name = str(field_type.chain[0])
            table_type = field_type.field_type.table_type
            keys = restricted_property_keys_for_table_type(table_type, self.context)
            if name in keys or native_property_path_overlaps_restriction(name, table_type, self.context):
                raise PermissionDenied("The filter uses a property your account cannot read.")
        elif isinstance(field_type, ast.FieldType):
            field = field_type.resolve_database_field(self.context)
            if not isinstance(field, DatabaseField):
                super().visit_field(node)
                return
            keys = restricted_property_keys_for_table_type(field_type.table_type, self.context)
            mirrored = mirrored_property_for_column(field_type.table_type, field.name, self.context)
            if mirrored is not None and mirrored in keys:
                raise PermissionDenied("The filter uses a property your account cannot read.")
            if field.name in RESTRICTABLE_JSON_BLOB_COLUMNS and keys:
                raise PermissionDenied(
                    "Property access is restricted. Filter on individual properties instead of a whole properties object."
                )
        super().visit_field(node)
