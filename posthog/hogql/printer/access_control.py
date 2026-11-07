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
    visible. The grant set comes from `UserAccessControl.allowlisted_resource_ids_by_scope`, shared
    with the cache-key fingerprint in query_runner.py. The deny set comes from
    `table.blocked_object_ids`, and the parent objects a child table's reader created come from
    `table.creator_owned_object_ids`. Both default to the rules on UserAccessControl.
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
        creator_owned_ids = table.creator_owned_object_ids(user_access_control, context.team_id, None) - allowlisted_ids
        if creator_owned_ids:
            guard = ast.Or(
                exprs=[
                    guard,
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=_id_as_string(id_field, table_type),
                        right=ast.Constant(value=sorted(creator_owned_ids), is_sensitive=True),
                        type=ast.BooleanType(),
                    ),
                ],
                type=ast.BooleanType(),
            )
    else:
        blocked_ids = table.blocked_object_ids(user_access_control, context.team_id)
        if blocked_ids:
            blocked_ids -= table.creator_owned_object_ids(user_access_control, context.team_id, blocked_ids)
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


# The resource that owns each `internal_source` value. A source missing here is hidden from everyone
# except organization admins, so add it here before its producer starts sending.
INTERNAL_LOG_SOURCE_RESOURCES: dict[str, "APIScopeObject"] = {"hog_flow": "hog_flow", "hog_function": "hog_function"}

# The service name each source's producer stamps, from `INTERNAL_SOURCE_POLICIES` in nodejs/src/logs/internal-logs.ts.
INTERNAL_LOG_SOURCE_SERVICES: dict[str, str] = {
    "hog_flow": "posthog-internal-workflows",
    "hog_function": "posthog-internal-hog-functions",
}


def readable_internal_log_sources(user_access_control: Optional["UserAccessControl"]) -> list[str]:
    """The internal log sources the user may read.

    The workflow and destination logs endpoints check access per object. The logs tables cannot map every
    row to its object, so this check fails closed: one denied object hides every row of its source.
    """
    if user_access_control is None:
        return []
    if user_access_control.is_organization_admin:
        return list(INTERNAL_LOG_SOURCE_RESOURCES)
    return [
        source
        for source, resource in INTERNAL_LOG_SOURCE_RESOURCES.items()
        if user_access_control.check_access_level_for_resource(resource, "viewer")
        and not user_access_control.blocked_resource_ids_by_scope.get(resource)
    ]


def build_internal_logs_guard(
    table_type: ast.TableOrSelectType, context: HogQLContext, has_internal_source: bool
) -> Optional[ast.Expr]:
    """Hides the internal log sources the user cannot read, unless the user reads every source."""
    user_access_control = context.database.user_access_control if context.database else None
    readable = readable_internal_log_sources(user_access_control)
    if len(readable) == len(INTERNAL_LOG_SOURCE_RESOURCES):
        return None

    def field(name: str) -> ast.Field:
        return ast.Field(chain=[name], type=ast.FieldType(name=name, table_type=table_type))

    # service_name is in the sort key, so this filter skips the hidden sources' granules. A customer row
    # that reuses an internal service name is hidden too, which never exposes anything.
    hidden_services = ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=field("service_name"),
        right=ast.Tuple(
            exprs=[
                ast.Constant(value=service)
                for source, service in INTERNAL_LOG_SOURCE_SERVICES.items()
                if source not in readable
            ]
        ),
        type=ast.BooleanType(),
    )
    if not has_internal_source:
        return hidden_services
    # Fails closed for a source that has no entry above yet.
    readable_sources = ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=field("internal_source"),
        right=ast.Tuple(exprs=[ast.Constant(value=source) for source in ["", *readable]]),
        type=ast.BooleanType(),
    )
    return ast.And(exprs=[hidden_services, readable_sources], type=ast.BooleanType())
