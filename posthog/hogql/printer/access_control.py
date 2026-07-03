from typing import Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.postgres_table import PostgresTable


def build_access_control_guard(
    table: PostgresTable,
    table_type: ast.TableOrSelectType,
    context: HogQLContext,
) -> Optional[ast.Expr]:
    """
    Build the WHERE clause AST node that filters out access-controlled resource IDs
    for the current user. Returns None if no filtering is needed.

    Deny set lives on UserAccessControl.blocked_resource_ids_by_scope — single source
    of truth, shared with the cache-key fingerprint in query_runner.py.
    """
    resource = table.access_scope
    if not resource:
        return None

    id_field = table.access_control_id
    if id_field is None:
        return None

    if not context.database or not context.database.user_access_control:
        return None

    blocked_ids = context.database.user_access_control.blocked_resource_ids_by_scope.get(resource, set())
    if not blocked_ids:
        return None

    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=ast.Call(
            name="toString",
            args=[ast.Field(chain=[id_field], type=ast.FieldType(name=id_field, table_type=table_type))],
        ),
        right=ast.Constant(value=sorted(blocked_ids), is_sensitive=True),
        type=ast.BooleanType(),
    )
