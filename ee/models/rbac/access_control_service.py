from typing import Optional

from django.db.models import QuerySet

from rest_framework import exceptions

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.rbac.user_access_control import (
    UserAccessControl,
    highest_access_level,
    minimum_access_level,
    ordered_access_levels,
)
from posthog.scopes import API_SCOPE_OBJECTS

from ee.models.rbac.access_control import AccessControl
from ee.models.rbac.role import Role


def resolve_role_by_name(organization: Organization, role_name: str) -> Role:
    role = Role.objects.filter(organization=organization, name=role_name).first()
    if not role:
        raise ValueError(f"Role '{role_name}' not found in this organization")
    return role


def resolve_member_by_email(organization: Organization, email: str) -> OrganizationMembership:
    membership = OrganizationMembership.objects.filter(
        organization=organization,
        user__email=email,
        user__is_active=True,
    ).first()
    if not membership:
        raise ValueError(f"User '{email}' not found in this organization")
    return membership


def validate_resource(resource: str) -> None:
    if resource not in API_SCOPE_OBJECTS:
        raise ValueError(f"Invalid resource: {resource}")


def validate_access_level(resource: str, access_level: str) -> None:
    levels = ordered_access_levels(resource)
    if access_level not in levels:
        raise ValueError(f"Invalid access level '{access_level}' for {resource}. Must be one of: {', '.join(levels)}")

    min_level = minimum_access_level(resource)
    if levels.index(access_level) < levels.index(min_level):
        raise ValueError(f"Access level cannot be set below the minimum '{min_level}' for {resource}")

    max_level = highest_access_level(resource)
    if levels.index(access_level) > levels.index(max_level):
        raise ValueError(f"Access level cannot be set above the maximum '{max_level}' for {resource}")


def _check_grant_permission(
    user: User,
    team: Team,
    resource: str,
    resource_id: Optional[str],
) -> None:
    uac = UserAccessControl(user=user, team=team)

    if resource_id:
        # For object-level grants, look up the object and check manager/admin access

        # Try to find the object by resource type and ID
        obj = _resolve_resource_object(team, resource, resource_id)
        if obj and not uac.check_can_modify_access_levels_for_object(obj):
            required_level = highest_access_level(resource)
            raise exceptions.PermissionDenied(f"Must be {required_level} to modify {resource} permissions.")
    else:
        # For project-wide resource defaults, require org admin
        if not uac.check_can_modify_access_levels_for_object(team):
            raise exceptions.PermissionDenied("Must be an Organization admin to modify project-wide permissions.")


def _resolve_resource_object(team: Team, resource: str, resource_id: str) -> Optional[object]:
    """Try to resolve a resource object by type and ID for permission checking."""

    # Map resource types to their model classes
    resource_model_map: dict[str, type] = {}

    try:
        from posthog.models import Dashboard, Insight
        from posthog.models.action import Action
        from posthog.models.experiment import Experiment
        from posthog.models.feature_flag import FeatureFlag
        from posthog.models.notebook.notebook import Notebook

        resource_model_map.update(
            {
                "dashboard": Dashboard,
                "insight": Insight,
                "action": Action,
                "experiment": Experiment,
                "feature_flag": FeatureFlag,
                "notebook": Notebook,
            }
        )
    except ImportError:
        pass

    model_class = resource_model_map.get(resource)
    if not model_class:
        return None

    return model_class.objects.filter(team=team, id=resource_id).first()


def grant_access(
    team: Team,
    user: User,
    resource: str,
    access_level: str,
    resource_id: Optional[str] = None,
    role: Optional[Role] = None,
    organization_member: Optional[OrganizationMembership] = None,
) -> AccessControl:
    validate_resource(resource)
    validate_access_level(resource, access_level)

    if role and organization_member:
        raise ValueError("Cannot scope an access control to both a member and a role.")

    _check_grant_permission(user, team, resource, resource_id)

    instance, created = AccessControl.objects.update_or_create(
        team=team,
        resource=resource,
        resource_id=resource_id,
        organization_member=organization_member,
        role=role,
        defaults={
            "access_level": access_level,
            "created_by": user,
        },
    )
    return instance


def revoke_access(
    team: Team,
    user: User,
    resource: str,
    resource_id: Optional[str] = None,
    role: Optional[Role] = None,
    organization_member: Optional[OrganizationMembership] = None,
) -> bool:
    validate_resource(resource)
    _check_grant_permission(user, team, resource, resource_id)

    deleted_count, _ = AccessControl.objects.filter(
        team=team,
        resource=resource,
        resource_id=resource_id,
        organization_member=organization_member,
        role=role,
    ).delete()
    return deleted_count > 0


def list_grants(
    team: Team,
    resource: Optional[str] = None,
    resource_id: Optional[str] = None,
    role: Optional[Role] = None,
    organization_member: Optional[OrganizationMembership] = None,
) -> QuerySet[AccessControl]:
    qs = AccessControl.objects.filter(team=team)

    if resource is not None:
        qs = qs.filter(resource=resource)
    if resource_id is not None:
        qs = qs.filter(resource_id=resource_id)
    if role is not None:
        qs = qs.filter(role=role)
    if organization_member is not None:
        qs = qs.filter(organization_member=organization_member)

    return qs.order_by("resource", "resource_id", "-created_at")
