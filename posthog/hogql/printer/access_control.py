"""
Object-level access control predicates for HogQL system tables.

The resource-level layer (`Database._filter_system_tables_for_user`) already
removes whole system tables the user has no access to. This module covers the
finer-grained case: a user has resource-level access (or has explicit grants
in the "none" + specific-allow pattern), but specific object IDs are denied or
allow-listed via `ee_accesscontrol` rows.

We express the filter as a subquery against the internal
`_posthog_internal_access_control` HogQL table — see
`posthog/hogql/database/schema/access_control_internal.py`. The generated
ClickHouse fetches the small `ee_accesscontrol` row set from Postgres at query
time and joins it against the system table.

Why a subquery instead of a literal `NOT IN (id1, id2, ...)`:

- No upper bound on the deny set — the literal approach hits the 1 MB CH query
  cap around ~25k IDs.
- The denied IDs never appear in `context.values`, so they cannot leak via the
  CH `system.query_log` or any echoed error.
- The precedence rules (default vs. explicit, role vs. member) live in one
  place — the SQL — instead of being re-implemented in Python.

The HogQL we emit roughly matches `filter_queryset_by_access_level` in
`posthog/rbac/user_access_control.py`. Two branches:

- ``has_resource_access``: emit a deny-list anti-filter
  ``toString(id) NOT IN (SELECT resource_id FROM <internal> ... blocked rules ...)``
- otherwise: emit an allow-list filter
  ``toString(id) IN (SELECT resource_id FROM <internal> ... allowed rules ...)``

Both branches OR in a creator-bypass clause when the underlying table has a
``created_by_id`` column.
"""

from typing import TYPE_CHECKING, Optional

from posthog.hogql import ast
from posthog.hogql.database.schema.access_control_internal import INTERNAL_ACCESS_CONTROL_TABLE_NAME
from posthog.hogql.parser import parse_expr

if TYPE_CHECKING:
    from posthog.hogql.database.postgres_table import PostgresTable

    from posthog.rbac.user_access_control import UserAccessControl
    from posthog.scopes import APIScopeObject


# `none` access level constant — kept inline to avoid an import cycle through
# `posthog.rbac.user_access_control` for the type-only consumers above.
_NO_ACCESS = "none"


def build_object_access_control_predicate(
    table: "PostgresTable",
    user_access_control: "UserAccessControl",
) -> Optional[ast.Expr]:
    """Build the object-level WHERE predicate for a single system table.

    Returns ``None`` when no filter is needed (admin user, no team context,
    resource has no ACL rules at all, etc.) — the printer skips appending it.
    """
    from posthog.models import OrganizationMembership

    resource = table.access_scope
    primary_key = table.primary_key
    if resource is None or primary_key is None:
        return None

    org_membership = user_access_control._organization_membership
    if org_membership is None:
        # Resource-level layer is the fail-closed guard for "no membership"; if
        # we ever reach the predicate layer without one, do not narrow further.
        return None

    # Org admins skip the filter entirely — matches the early-return in
    # `filter_queryset_by_access_level(include_all_if_admin=True)` semantics
    # and in `_filter_system_tables_for_user`.
    if org_membership.level >= OrganizationMembership.Level.ADMIN:
        return None

    if user_access_control._team is None:
        return None

    # Cheap short-circuit: if the team has no `ee_accesscontrol` rows for this
    # resource type at all, no object can be filtered. Avoids the cross-DB
    # subquery in the overwhelmingly common case where nobody has configured
    # object-level RBAC for this resource.
    if not user_access_control.has_access_levels_for_resource(resource):
        return None

    resource_access_level = user_access_control.access_level_for_resource(resource)
    has_resource_access = bool(resource_access_level) and resource_access_level != _NO_ACCESS

    user_member_id = str(org_membership.id)
    user_role_ids = [str(r) for r in user_access_control._user_role_ids]
    created_by_id = _created_by_id_field(table)

    if has_resource_access:
        guard = _build_deny_list_predicate(
            resource=resource,
            primary_key=primary_key,
            user_member_id=user_member_id,
            user_role_ids=user_role_ids,
        )
    else:
        guard = _build_allow_list_predicate(
            resource=resource,
            primary_key=primary_key,
            user_member_id=user_member_id,
            user_role_ids=user_role_ids,
        )

    if created_by_id is not None and user_access_control._user is not None:
        # Creator bypass: a user always sees rows they own. Matches the
        # `Q(created_by=self._user)` OR in `filter_queryset_by_access_level`.
        guard = ast.Or(
            exprs=[
                guard,
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[created_by_id]),
                    right=ast.Constant(value=user_access_control._user.id),
                ),
            ]
        )

    return guard


def _created_by_id_field(table: "PostgresTable") -> Optional[str]:
    """Return the name of the `created_by_id` column on the table, if exposed.

    The system tables expose this column inconsistently (some name it
    `created_by`, some `created_by_id`, some don't expose it at all). We only
    enable the creator bypass when the column is actually queryable from
    HogQL — otherwise the predicate would fail to resolve.
    """
    for candidate in ("created_by_id", "created_by"):
        if candidate in table.fields:
            return candidate
    return None


def _user_relevance_filter_expr(
    user_member_id: str,
    user_role_ids: list[str],
) -> ast.Expr:
    """The "rows applying to this user" filter — mirrors `_filter_options`."""

    if user_role_ids:
        # Wrap the role-list comparison so we can re-use it both inside and
        # outside the role-matched branch.
        role_filter = parse_expr(
            "role_id IN {role_ids}",
            placeholders={"role_ids": ast.Tuple(exprs=[ast.Constant(value=r) for r in user_role_ids])},
        )
    else:
        # `IN ()` is invalid SQL; emit `1=0` so the role branch contributes
        # nothing. The outer OR still picks up default + member rows.
        role_filter = ast.Constant(value=False)

    return parse_expr(
        """
        (isNull(organization_member_id) AND isNull(role_id))
        OR (organization_member_id = {member_id} AND isNull(role_id))
        OR (isNull(organization_member_id) AND {role_filter})
        """,
        placeholders={
            "member_id": ast.Constant(value=user_member_id),
            "role_filter": role_filter,
        },
    )


def _explicit_row_expr() -> ast.Expr:
    """Mirrors Python's `ac.role is not None or ac.organization_member is not None`."""
    return parse_expr("isNotNull(organization_member_id) OR isNotNull(role_id)")


def _build_deny_list_predicate(
    *,
    resource: "APIScopeObject",
    primary_key: str,
    user_member_id: str,
    user_role_ids: list[str],
) -> ast.Expr:
    """Emit ``toString(<pk>) NOT IN (<blocked-rows subquery>)``.

    The HAVING clause matches `filter_queryset_by_access_level`'s deny
    semantics:

    - if there is any explicit role/member ACL row and *all* explicit rows are
      `none` → BLOCKED
    - if there are *no* explicit rows but *all* default rows are `none`
      → BLOCKED
    """
    subquery = parse_expr(
        f"""
        (
            SELECT resource_id
            FROM {INTERNAL_ACCESS_CONTROL_TABLE_NAME}
            WHERE
                resource = {{resource}}
                AND isNotNull(resource_id)
                AND ({{user_relevance}})
            GROUP BY resource_id
            HAVING
                (
                    countIf({{is_explicit}}) > 0
                    AND countIf({{is_explicit}} AND access_level != {{none}}) = 0
                )
                OR (
                    countIf({{is_explicit}}) = 0
                    AND count() > 0
                    AND countIf(access_level != {{none}}) = 0
                )
        )
        """,
        placeholders={
            "resource": ast.Constant(value=resource),
            "user_relevance": _user_relevance_filter_expr(user_member_id, user_role_ids),
            "is_explicit": _explicit_row_expr(),
            "none": ast.Constant(value=_NO_ACCESS),
        },
    )

    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=ast.Call(name="toString", args=[ast.Field(chain=[primary_key])]),
        right=subquery,
    )


def _build_allow_list_predicate(
    *,
    resource: "APIScopeObject",
    primary_key: str,
    user_member_id: str,
    user_role_ids: list[str],
) -> ast.Expr:
    """Emit ``toString(<pk>) IN (<allowed-rows subquery>)``.

    Mirrors the allow-list branch of `filter_queryset_by_access_level`:
    a resource_id is allowed when it has at least one explicit role/member ACL
    row with a non-`none` access level.
    """
    subquery = parse_expr(
        f"""
        (
            SELECT resource_id
            FROM {INTERNAL_ACCESS_CONTROL_TABLE_NAME}
            WHERE
                resource = {{resource}}
                AND isNotNull(resource_id)
                AND ({{user_relevance}})
            GROUP BY resource_id
            HAVING countIf({{is_explicit}} AND access_level != {{none}}) > 0
        )
        """,
        placeholders={
            "resource": ast.Constant(value=resource),
            "user_relevance": _user_relevance_filter_expr(user_member_id, user_role_ids),
            "is_explicit": _explicit_row_expr(),
            "none": ast.Constant(value=_NO_ACCESS),
        },
    )

    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Call(name="toString", args=[ast.Field(chain=[primary_key])]),
        right=subquery,
    )
