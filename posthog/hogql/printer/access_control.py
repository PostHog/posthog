from collections.abc import Iterable
from typing import TYPE_CHECKING, Optional

import humanize

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.postgres_table import PostgresTable

from posthog.rbac.user_access_control import resource_to_display_name

if TYPE_CHECKING:
    from posthog.schema import AccessControlFilterWarning


def build_access_control_warning(resources: Iterable[str]) -> Optional["AccessControlFilterWarning"]:
    """Turn the restricted resources a query referenced into the single user-facing warning.

    We can't tell whether rows were actually excluded — the guard is pushed into SQL, so the DB never
    returns them — only that the user has restrictions on these resources. Hence "may exclude".
    """
    from posthog.schema import (
        AccessControlFilterWarning,  # noqa: PLC0415 — keeps posthog.schema off django.setup() via this module
    )

    sorted_resources = sorted(resources)
    if not sorted_resources:
        return None
    display_names = humanize.natural_list([resource_to_display_name(r) for r in sorted_resources])
    return AccessControlFilterWarning(
        resources=sorted_resources,
        message=f"Results may exclude {display_names} you don't have access to",
    )


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

    # Surface that this query is subject to filtering so callers don't mistake a possibly-partial
    # result for the full set. Note the guard applying doesn't mean rows were actually excluded —
    # the user's blocked objects may not have matched the query anyway.
    context.access_control_restricted_resources.add(resource)

    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=ast.Call(
            name="toString",
            args=[ast.Field(chain=[id_field], type=ast.FieldType(name=id_field, table_type=table_type))],
        ),
        right=ast.Constant(value=sorted(blocked_ids), is_sensitive=True),
        type=ast.BooleanType(),
    )
