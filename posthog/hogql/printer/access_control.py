"""HogQL object-level access control guard.

Emits a `NOT IN (SELECT resource_id FROM ee_accesscontrol WHERE ... GROUP BY ... HAVING ...)`
subquery against the live Postgres `ee_accesscontrol` table for every system table query
made by a non-admin user.

Why a subquery and not a literal `NOT IN (id1, id2, ...)` list?
- C1: a literal list is unbounded (CH 1 MB query cap hits at ~25k IDs). The subquery
  approach is bounded by per-team `ee_accesscontrol` row count.
- C2: literal IDs leak into `system.query_log` server-side. The subquery only embeds
  the calling user's own membership UUID and role UUIDs as parameters.

Why a private (unregistered) `PostgresTable` instance?
- The `ee_accesscontrol` table content leaks org structure (who is locked out of what).
  Keeping it off the public HogQL schema prevents accidental exposure through
  autocomplete, MCP, OAuth scopes, and the SQL editor. Only this printer references it.
"""

from typing import TYPE_CHECKING, Optional

import posthoganalytics
from opentelemetry import trace
from prometheus_client import Counter

from posthog.hogql import ast
from posthog.hogql.database.models import IntegerDatabaseField, StringDatabaseField
from posthog.hogql.database.postgres_table import PostgresTable

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext


HOGQL_OBJECT_ACCESS_CONTROL_FLAG = "hogql-object-access-control"

tracer = trace.get_tracer(__name__)

ACL_SUBQUERY_EMITTED_COUNTER = Counter(
    "posthog_hogql_acl_subquery_emitted_total",
    "Count of HogQL queries where an object-level access control subquery was emitted",
    labelnames=["resource"],
)


# Private. Never registered on the HogQL Database. Only this module instantiates AST nodes
# pointing at it; the printer renders it via `to_printed_clickhouse(context)` which emits a
# `postgresql(...)` function call with credentials masked through `add_sensitive_value`.
_access_controls_table = PostgresTable(
    name="access_controls",
    postgres_table_name="ee_accesscontrol",
    fields={
        "team_id": IntegerDatabaseField(name="team_id"),
        "resource": StringDatabaseField(name="resource"),
        "resource_id": StringDatabaseField(name="resource_id", nullable=True),
        "organization_member_id": StringDatabaseField(name="organization_member_id", nullable=True),
        "role_id": StringDatabaseField(name="role_id", nullable=True),
        "access_level": StringDatabaseField(name="access_level"),
    },
)


def _is_object_acl_enabled(context: "HogQLContext") -> bool:
    """Evaluate the feature flag once per query and cache on the context."""
    if context._object_acl_flag_resolved is not None:
        return context._object_acl_flag_resolved

    team = context.team
    if team is None:
        context._object_acl_flag_resolved = False
        return False

    enabled = bool(
        posthoganalytics.feature_enabled(
            HOGQL_OBJECT_ACCESS_CONTROL_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            send_feature_flag_events=False,
        )
    )
    context._object_acl_flag_resolved = enabled
    return enabled


def _build_access_controls_subquery(
    resource: str,
    team_id: int,
    member_id: str,
    role_ids: list[str],
) -> ast.SelectQuery:
    """Construct the typed AST for:

    SELECT resource_id FROM ee_accesscontrol
    WHERE team_id = $team_id
      AND resource = $resource
      AND isNotNull(resource_id)
      AND (
        (isNull(organization_member_id) AND isNull(role_id))
        OR organization_member_id = $member_id
        [OR role_id IN ($role_ids)]   -- only if role_ids non-empty
      )
    GROUP BY resource_id
    HAVING
      if(
        max(toUInt8(isNotNull(organization_member_id) OR isNotNull(role_id))),
        -- explicit rows exist: blocked iff every explicit row is 'none'
        max(if(isNotNull(organization_member_id) OR isNotNull(role_id), access_level != 'none', 0)) = 0,
        -- only default rows present: blocked iff every default row is 'none'
        max(access_level != 'none') = 0
      )
    """
    # The printer only emits `AS <alias>` when the JoinExpr's type is a TableAliasType — see
    # `BasePrinter.visit_join_expr` around the `isinstance(node.type, (ast.TableAliasType, ...))`
    # branch. Without an alias, field qualifiers (`access_controls.team_id`) would not bind to
    # anything in CH because the FROM resolves to `postgresql(...)`, not to a named table.
    base_type = ast.TableType(table=_access_controls_table)
    ac_alias = "access_controls"
    ac_type = ast.TableAliasType(alias=ac_alias, table_type=base_type)

    def ac_field(name: str) -> ast.Field:
        # The chain doesn't drive SQL output (visit_field delegates to node.type for that). We
        # match the pattern in `team_id_guard_for_table` — single-segment chain, fully-typed.
        return ast.Field(chain=[name], type=ast.FieldType(name=name, table_type=ac_type))

    is_explicit = ast.Or(
        exprs=[
            ast.Call(name="isNotNull", args=[ac_field("organization_member_id")]),
            ast.Call(name="isNotNull", args=[ac_field("role_id")]),
        ]
    )

    is_default = ast.And(
        exprs=[
            ast.Call(name="isNull", args=[ac_field("organization_member_id")]),
            ast.Call(name="isNull", args=[ac_field("role_id")]),
        ]
    )

    member_match = ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ac_field("organization_member_id"),
        right=ast.Constant(value=member_id),
    )

    applies_to_user_exprs: list[ast.Expr] = [is_default, member_match]
    if role_ids:
        applies_to_user_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ac_field("role_id"),
                right=ast.Tuple(exprs=[ast.Constant(value=rid) for rid in role_ids]),
            )
        )
    applies_to_user = ast.Or(exprs=applies_to_user_exprs)

    where = ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ac_field("team_id"),
                right=ast.Constant(value=team_id),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ac_field("resource"),
                right=ast.Constant(value=resource),
            ),
            ast.Call(name="isNotNull", args=[ac_field("resource_id")]),
            applies_to_user,
        ]
    )

    access_level_not_none = ast.CompareOperation(
        op=ast.CompareOperationOp.NotEq,
        left=ac_field("access_level"),
        right=ast.Constant(value="none"),
    )

    # Branch 1 (explicit rows exist): blocked iff every explicit row is 'none'.
    # Use `if(is_explicit, access_level != 'none', 0)` so default rows contribute 0 (don't
    # mask the explicit-tier decision).
    branch_explicit = ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Call(
            name="max",
            args=[
                ast.Call(
                    name="if",
                    args=[is_explicit, access_level_not_none, ast.Constant(value=0)],
                )
            ],
        ),
        right=ast.Constant(value=0),
    )

    # Branch 2 (no explicit rows): only default rows survived the WHERE filter; blocked iff every
    # default row is 'none'.
    branch_default = ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Call(name="max", args=[access_level_not_none]),
        right=ast.Constant(value=0),
    )

    # `if(has_any_explicit_row, branch_explicit, branch_default)` — explicit rows override defaults.
    having = ast.Call(
        name="if",
        args=[
            ast.Call(name="max", args=[ast.Call(name="toUInt8", args=[is_explicit])]),
            branch_explicit,
            branch_default,
        ],
    )

    return ast.SelectQuery(
        select=[ac_field("resource_id")],
        select_from=ast.JoinExpr(
            table=ast.Field(chain=[ac_alias]),
            alias=ac_alias,
            type=ac_type,
        ),
        where=where,
        group_by=[ac_field("resource_id")],
        having=having,
    )


def build_access_control_guard(
    table: PostgresTable,
    table_type: ast.TableOrSelectType,
    context: "HogQLContext",
) -> Optional[ast.Expr]:
    """Build the `notIn(toString(pk), <subquery>)` guard for a system PostgresTable.

    Returns None when the guard is not applicable (bypassed).
    Returns `Constant(value=False)` when we fail closed (user context expected but missing membership).
    """
    from posthog.models import OrganizationMembership

    resource = table.access_scope
    if not resource:
        return None  # Table is not RBAC-controlled (e.g. system.numbers).

    pk = table.primary_key
    if pk is None:
        return None  # Composite PK or introspection failure — can't safely build the guard.

    if not context.team or not context.team_id:
        return None  # System queries / exports with no team context — handled by other gates.

    if context.database is None or context.database.user_access_control is None:
        return None  # No user on the context — existing resource-level filter is fail-closed already.

    uac = context.database.user_access_control

    if not uac.access_controls_supported:
        return None  # EE not installed / org doesn't have the ACCESS_CONTROL feature.

    org_membership = uac._organization_membership
    if org_membership is None:
        # Should be impossible: the resource-level filter already ran and would have hidden the
        # table for a user who isn't a member of this team's org. Fail closed defensively.
        return ast.Constant(value=False)

    # Bypass: org admins see everything.
    if org_membership.level >= OrganizationMembership.Level.ADMIN:
        return None

    # Bypass: project admins see everything (same as REST behavior).
    if uac.check_access_level_for_object(context.team, required_level="admin", explicit=True):
        return None

    if not _is_object_acl_enabled(context):
        return None  # Kill-switch.

    role_ids = [str(rid) for rid in uac._user_role_ids]
    member_id = str(org_membership.id)

    with tracer.start_as_current_span("rbac.acl_subquery") as span:
        span.set_attribute("rbac.resource", resource)
        span.set_attribute("rbac.acl_subquery.emitted", True)
        ACL_SUBQUERY_EMITTED_COUNTER.labels(resource=resource).inc()

        subquery = _build_access_controls_subquery(
            resource=resource,
            team_id=context.team_id,
            member_id=member_id,
            role_ids=role_ids,
        )

        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotIn,
            left=ast.Call(
                name="toString",
                args=[ast.Field(chain=[pk], type=ast.FieldType(name=pk, table_type=table_type))],
            ),
            right=subquery,
            type=ast.BooleanType(),
        )
