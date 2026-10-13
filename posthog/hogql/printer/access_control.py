from collections.abc import Iterable
from typing import TYPE_CHECKING, Optional

import humanize

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.postgres_table import PostgresTable

if TYPE_CHECKING:
    from posthog.schema import AccessControlFilterWarning

    from posthog.scopes import APIScopeObject

    from products.authz.backend.facade.contracts import AccessFilter


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
    """Build the WHERE guard that narrows the table to the rows the current user may query, or None.

    The decision comes from the authz facade as an `AccessFilter`. This function only turns it into
    an expression, because only the table knows its id and creator columns.
    """
    resource = table.access_scope
    if not resource:
        return None

    id_field = table.access_control_id
    if id_field is None:
        return None

    if not context.database or not context.database.user_access_control:
        return None

    from products.authz.backend.facade import api as authz  # noqa: PLC0415
    from products.authz.backend.facade.contracts import Resource, Subject  # noqa: PLC0415
    from products.authz.backend.facade.enums import Action, ResourceType  # noqa: PLC0415

    user_access_control = context.database.user_access_control
    user_id = user_access_control.user.pk
    creator_field = table.access_control_creator_id
    access_filter = authz.filter(
        resource=Resource(type=ResourceType(resource), project_id=context.team_id),
        action=Action.QUERY,
        subject=Subject(user_id=user_id),
        creator_exempt=creator_field is not None and creator_field in table.fields,
        user_access_control=user_access_control,
    )
    guard = filter_to_expr(access_filter, id_field, table_type, creator_field, user_id)
    if guard is None:
        return None

    # Surface that this query is subject to filtering so callers don't mistake a possibly-partial
    # result for the full set. Note the guard applying doesn't mean rows were actually excluded —
    # the user's blocked objects may not have matched the query anyway.
    context.access_control_restricted_resources.add(resource)

    return guard


def filter_to_expr(
    access_filter: "AccessFilter",
    id_field: str,
    table_type: ast.TableOrSelectType,
    creator_field: Optional[str],
    subject_user_id: Optional[int],
) -> Optional[ast.Expr]:
    """Translate an authz filter into the WHERE guard for one table, or None when nothing is restricted.

    Pure: it knows the column names and the AST, and nothing about the rules. Mirrors
    `posthog.models.access_filter.apply_filter`, the QuerySet adapter.
    """
    from products.authz.backend.facade.enums import FilterKind  # noqa: PLC0415

    if access_filter.kind == FilterKind.ALL:
        return None

    if access_filter.kind == FilterKind.NONE:
        guard: ast.Expr = ast.Constant(value=False)
    else:
        guard = ast.CompareOperation(
            op=ast.CompareOperationOp.In if access_filter.kind == FilterKind.ONLY else ast.CompareOperationOp.NotIn,
            left=_id_as_string(id_field, table_type),
            right=ast.Constant(value=sorted(access_filter.ids), is_sensitive=True),
            type=ast.BooleanType(),
        )

    if access_filter.creator_exempt and creator_field is not None and subject_user_id is not None:
        exemption = _build_creator_exemption(creator_field, table_type, subject_user_id)
        guard = ast.Or(exprs=[guard, exemption], type=ast.BooleanType())

    return guard


def _id_as_string(id_field: str, table_type: ast.TableOrSelectType) -> ast.Expr:
    """Object id as a string, because access control stores `resource_id` as text."""
    return ast.Call(
        name="toString",
        args=[ast.Field(chain=[id_field], type=ast.FieldType(name=id_field, table_type=table_type))],
    )


def _build_creator_exemption(
    creator_field: str,
    table_type: ast.TableOrSelectType,
    subject_user_id: int,
) -> ast.Expr:
    """`created_by_id = <current user>`, the REST creator exemption.

    A NULL creator must not exempt the row, hence the ifNull: without it the comparison is NULL and
    takes the whole OR with it.
    """
    return ast.Call(
        name="ifNull",
        args=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[creator_field], type=ast.FieldType(name=creator_field, table_type=table_type)),
                right=ast.Constant(value=subject_user_id),
                type=ast.BooleanType(),
            ),
            ast.Constant(value=False),
        ],
    )
