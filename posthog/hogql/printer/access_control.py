from collections.abc import Iterable
from typing import TYPE_CHECKING, Optional

import humanize

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.postgres_table import PostgresTable

if TYPE_CHECKING:
    from posthog.schema import AccessControlFilterWarning

    from posthog.scopes import APIScopeObject

    from products.access_control.backend.facade.user_access_control import UserAccessControl


def build_access_control_warning(resources: Iterable["APIScopeObject"]) -> Optional["AccessControlFilterWarning"]:
    """Turn the restricted resources a query referenced into the single user-facing warning.

    We can't tell whether rows were actually excluded — the guard is pushed into SQL, so the DB never
    returns them — only that the user has restrictions on these resources. Hence "may exclude".
    """
    from posthog.schema import (
        AccessControlFilterWarning,  # noqa: PLC0415 — keeps posthog.schema off django.setup() via this module
    )

    from products.access_control.backend.facade.user_access_control import resource_to_display_name  # noqa: PLC0415

    sorted_resources = sorted(resources)
    if not sorted_resources:
        return None
    display_names = humanize.natural_list([resource_to_display_name(r) for r in sorted_resources])
    return AccessControlFilterWarning(
        resources=[str(r) for r in sorted_resources],
        message=f"Results may exclude {display_names} you don't have access to",
    )


def build_access_control_guard(
    table: PostgresTable,
    table_type: ast.TableOrSelectType,
    context: HogQLContext,
) -> Optional[ast.Expr]:
    """
    Build the WHERE clause AST node that restricts the table to the access-controlled objects the
    current user may read. Returns None if no filtering is needed.

    Mirrors `UserAccessControl.filter_queryset_by_access_level`, the REST equivalent, branch for
    branch: with no resource-level access the rows are narrowed to the user's explicit grants,
    otherwise the objects denied to them are removed, and either way the objects they created stay
    visible. The id sets live on UserAccessControl (`allowlisted_resource_ids_by_scope` /
    `blocked_resource_ids_by_scope`) — single source of truth, shared with the cache-key fingerprint
    in query_runner.py.
    """
    resource = table.access_scope
    if not resource:
        return None

    id_field = table.access_control_id
    if id_field is None:
        return None

    if not context.database or not context.database.user_access_control:
        return None

    user_access_control = context.database.user_access_control

    allowlisted_ids = user_access_control.allowlisted_resource_ids_by_scope.get(resource)
    if allowlisted_ids:
        # No resource-level access at all: only the explicitly granted objects are readable.
        guard: ast.Expr = ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=_id_as_string(id_field, table_type),
            right=ast.Constant(value=sorted(allowlisted_ids), is_sensitive=True),
            type=ast.BooleanType(),
        )
    else:
        blocked_ids = user_access_control.blocked_resource_ids_by_scope.get(resource, frozenset())
        if not blocked_ids:
            return None
        guard = ast.CompareOperation(
            op=ast.CompareOperationOp.NotIn,
            left=_id_as_string(id_field, table_type),
            right=ast.Constant(value=sorted(blocked_ids), is_sensitive=True),
            type=ast.BooleanType(),
        )

    creator_exemption = _build_creator_exemption(table, table_type, user_access_control)
    if creator_exemption is not None:
        guard = ast.Or(exprs=[guard, creator_exemption], type=ast.BooleanType())

    # Surface that this query is subject to filtering so callers don't mistake a possibly-partial
    # result for the full set. Note the guard applying doesn't mean rows were actually excluded —
    # the user's blocked objects may not have matched the query anyway.
    context.access_control_restricted_resources.add(resource)

    return guard


def _id_as_string(id_field: str, table_type: ast.TableOrSelectType) -> ast.Expr:
    """Object id as a string, because access control stores `resource_id` as text."""
    return ast.Call(
        name="toString",
        args=[ast.Field(chain=[id_field], type=ast.FieldType(name=id_field, table_type=table_type))],
    )


def _build_creator_exemption(
    table: PostgresTable,
    table_type: ast.TableOrSelectType,
    user_access_control: "UserAccessControl",
) -> Optional[ast.Expr]:
    """`created_by_id = <current user>`, the REST creator exemption, or None when it can't apply.

    A NULL creator must not exempt the row, hence the ifNull: without it the comparison is NULL and
    takes the whole OR with it.
    """
    creator_field = table.access_control_creator_id
    if creator_field is None or creator_field not in table.fields:
        return None

    return ast.Call(
        name="ifNull",
        args=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[creator_field], type=ast.FieldType(name=creator_field, table_type=table_type)),
                right=ast.Constant(value=user_access_control.user.pk),
                type=ast.BooleanType(),
            ),
            ast.Constant(value=False),
        ],
    )
