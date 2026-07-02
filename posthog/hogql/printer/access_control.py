from typing import Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.postgres_table import PostgresTable

from posthog.rbac.user_access_control import resource_to_display_name


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

    # Surface that filtering happened so callers don't mistake a partial result for the full set. The
    # header carries the "excluded because no access" framing; the message just enumerates per resource.
    # The number reflects inaccessible objects excluded by the predicate, not rows dropped from this
    # result — filtering is pushed into SQL, so the DB never returns the filtered rows.
    count = len(blocked_ids)
    # resource_to_display_name is always plural; drop the trailing "s" for a single object.
    display_name = resource_to_display_name(resource)
    label = display_name[:-1] if count == 1 and display_name.endswith("s") else display_name
    context.add_access_control_warning(resource=resource, message=f"{count} {label}")

    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=ast.Call(
            name="toString",
            args=[ast.Field(chain=[id_field], type=ast.FieldType(name=id_field, table_type=table_type))],
        ),
        right=ast.Constant(value=sorted(blocked_ids), is_sensitive=True),
        type=ast.BooleanType(),
    )
