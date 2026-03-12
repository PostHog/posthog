from typing import Optional

from rest_framework import exceptions

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.errors import QueryError

from posthog.models import User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.personal_api_key_service import (
    create_personal_api_key,
    list_personal_api_keys,
    roll_personal_api_key,
    validate_scopes,
)
from posthog.models.team.team import Team


def execute_command(
    node: ast.Expr,
    user: User,
    team: Optional[Team] = None,
) -> HogQLQueryResponse:
    # API key commands
    if isinstance(node, ast.CreateApiKeyCommand):
        return _execute_create_api_key(node, user)

    if isinstance(node, ast.ShowApiKeysCommand):
        return _execute_show_api_keys(user)

    if isinstance(node, ast.AlterApiKeyRollCommand):
        return _execute_alter_api_key_roll(node, user)

    # Access control commands — require team
    if isinstance(node, (ast.GrantCommand, ast.RevokeCommand, ast.ShowGrantsCommand)):
        if team is None:
            raise QueryError("Access control commands require a project context")
        return _execute_access_control_command(node, user, team)

    raise QueryError(f"Unknown command type: {type(node).__name__}")


# --- API key command handlers ---


def _execute_create_api_key(node: ast.CreateApiKeyCommand, user: User) -> HogQLQueryResponse:
    try:
        validate_scopes(node.scopes)
    except ValueError as e:
        raise QueryError(str(e))
    try:
        key, raw_value = create_personal_api_key(user, node.label, node.scopes)
    except ValueError as e:
        raise QueryError(str(e))
    return HogQLQueryResponse(
        results=[[raw_value, key.label, key.scopes, str(key.created_at)]],
        columns=["api_key", "label", "scopes", "created_at"],
        types=["String", "String", "Array(String)", "DateTime"],
    )


def _execute_show_api_keys(user: User) -> HogQLQueryResponse:
    keys = list_personal_api_keys(user)
    rows = [
        [
            str(k.id),
            k.label,
            k.mask_value,
            k.scopes or ["*"],
            str(k.created_at),
            str(k.last_used_at) if k.last_used_at else None,
            str(k.last_rolled_at) if k.last_rolled_at else None,
        ]
        for k in keys
    ]
    return HogQLQueryResponse(
        results=rows,
        columns=["id", "label", "mask_value", "scopes", "created_at", "last_used_at", "last_rolled_at"],
        types=["String", "String", "String", "Array(String)", "DateTime", "DateTime", "DateTime"],
    )


def _execute_alter_api_key_roll(node: ast.AlterApiKeyRollCommand, user: User) -> HogQLQueryResponse:
    key = PersonalAPIKey.objects.filter(user=user, label=node.label).first()
    if not key:
        raise QueryError(f"API key '{node.label}' not found")
    key, raw_value = roll_personal_api_key(key)
    return HogQLQueryResponse(
        results=[[raw_value, key.label, str(key.last_rolled_at)]],
        columns=["api_key", "label", "last_rolled_at"],
        types=["String", "String", "DateTime"],
    )


# --- Access control command handlers ---


def _resolve_resource_name_to_id(
    team: Team,
    resource: str,
    resource_name: Optional[str],
) -> Optional[str]:
    """Convert a human-readable resource name to an ID, or return None if no name given."""
    if resource_name is None:
        return None
    try:
        from ee.models.rbac.access_control_service import resolve_resource_by_name

        return resolve_resource_by_name(team, resource, resource_name)
    except ImportError:
        raise QueryError("Access control commands require an Enterprise license")
    except ValueError as e:
        raise QueryError(str(e))


def _execute_access_control_command(
    node: ast.Expr,
    user: User,
    team: Team,
) -> HogQLQueryResponse:
    try:
        from ee.models.rbac.access_control_service import (
            get_resource_name,
            grant_access,
            list_grants,
            resolve_member_by_email,
            resolve_role_by_name,
            revoke_access,
        )
    except ImportError:
        raise QueryError("Access control commands require an Enterprise license")

    if isinstance(node, ast.GrantCommand):
        resource_id = _resolve_resource_name_to_id(team, node.resource, node.resource_name)
        return _execute_grant(
            node, user, team, resource_id, grant_access, resolve_role_by_name, resolve_member_by_email
        )

    if isinstance(node, ast.RevokeCommand):
        resource_id = _resolve_resource_name_to_id(team, node.resource, node.resource_name)
        return _execute_revoke(
            node, user, team, resource_id, revoke_access, resolve_role_by_name, resolve_member_by_email
        )

    if isinstance(node, ast.ShowGrantsCommand):
        resource_id = _resolve_resource_name_to_id(team, node.resource, node.resource_name) if node.resource else None
        return _execute_show_grants(
            node, team, resource_id, list_grants, get_resource_name, resolve_role_by_name, resolve_member_by_email
        )

    raise QueryError(f"Unknown access control command: {type(node).__name__}")


def _resolve_target(node, team, resolve_role_by_name, resolve_member_by_email):
    """Resolve a GRANT/REVOKE target into (role, organization_member) kwargs."""
    role = None
    organization_member = None

    if node.target_type == "role":
        role = resolve_role_by_name(team.organization, node.target_name)
    elif node.target_type == "user":
        organization_member = resolve_member_by_email(team.organization, node.target_name)
    # "default" → both stay None (project-wide default)

    return {"role": role, "organization_member": organization_member}


def _execute_grant(node, user, team, resource_id, grant_access, resolve_role_by_name, resolve_member_by_email):
    try:
        target_kwargs = _resolve_target(node, team, resolve_role_by_name, resolve_member_by_email)
        ac = grant_access(
            team=team,
            user=user,
            resource=node.resource,
            access_level=node.access_level,
            resource_id=resource_id,
            **target_kwargs,
        )
    except ValueError as e:
        raise QueryError(str(e))
    except exceptions.PermissionDenied as e:
        raise QueryError(str(e.detail))

    return HogQLQueryResponse(
        results=[
            [
                ac.resource,
                node.resource_name or ac.resource_id,
                ac.access_level,
                node.target_type,
                node.target_name,
                "granted",
            ]
        ],
        columns=["resource", "resource_name", "access_level", "target_type", "target_name", "status"],
        types=["String", "String", "String", "String", "String", "String"],
    )


def _execute_revoke(node, user, team, resource_id, revoke_access, resolve_role_by_name, resolve_member_by_email):
    try:
        target_kwargs = _resolve_target(node, team, resolve_role_by_name, resolve_member_by_email)
        deleted = revoke_access(
            team=team,
            user=user,
            resource=node.resource,
            resource_id=resource_id,
            **target_kwargs,
        )
    except ValueError as e:
        raise QueryError(str(e))
    except exceptions.PermissionDenied as e:
        raise QueryError(str(e.detail))

    status = "revoked" if deleted else "not_found"
    return HogQLQueryResponse(
        results=[
            [
                node.resource,
                node.resource_name,
                node.target_type,
                node.target_name,
                status,
            ]
        ],
        columns=["resource", "resource_name", "target_type", "target_name", "status"],
        types=["String", "String", "String", "String", "String"],
    )


def _execute_show_grants(
    node, team, resource_id, list_grants, get_resource_name, resolve_role_by_name, resolve_member_by_email
):
    try:
        role = None
        organization_member = None
        if node.filter_type == "role":
            role = resolve_role_by_name(team.organization, node.filter_name)
        elif node.filter_type == "user":
            organization_member = resolve_member_by_email(team.organization, node.filter_name)

        grants = list_grants(
            team=team,
            resource=node.resource,
            resource_id=resource_id,
            role=role,
            organization_member=organization_member,
        )
    except ValueError as e:
        raise QueryError(str(e))

    rows = []
    for g in grants.select_related("role", "organization_member__user"):
        target_type = "default"
        target_name = None
        if g.role_id:
            target_type = "role"
            target_name = g.role.name if g.role else str(g.role_id)
        elif g.organization_member_id:
            target_type = "user"
            target_name = g.organization_member.user.email if g.organization_member else str(g.organization_member_id)

        # Resolve the stored resource_id back to a human-readable name
        display_name = None
        if g.resource_id and g.resource:
            display_name = get_resource_name(team, g.resource, g.resource_id)
        display_name = display_name or g.resource_id

        rows.append(
            [
                g.resource,
                display_name,
                g.access_level,
                target_type,
                target_name,
                str(g.created_at),
            ]
        )

    return HogQLQueryResponse(
        results=rows,
        columns=["resource", "resource_name", "access_level", "target_type", "target_name", "created_at"],
        types=["String", "String", "String", "String", "String", "DateTime"],
    )
