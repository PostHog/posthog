# ruff: noqa
from posthog.models import OrganizationMembership
from posthog.models import OrganizationMembership as Membership
from posthog.user_permissions import UserPermissions as Permissions

from products.access_control.backend.facade.user_access_control import UserAccessControl as Access
from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.enums import Action


def direct_authorization(user, team, obj, view, membership):
    # ruleid: authorization-through-sdk
    access = Access(user=user, team=team)
    # ruleid: authorization-through-sdk
    permissions = Permissions(user)
    # ruleid: authorization-through-sdk
    access.check_access_level_for_object(obj, "editor")
    # ruleid: authorization-through-sdk
    view.user_access_control.check_access_level_for_resource("insight", "viewer")
    # ruleid: authorization-through-sdk
    view.user_access_control.assert_access_level_for_resource("insight", "viewer")
    # ruleid: authorization-through-sdk
    access.check_access_level_for_ref(ref, "viewer")
    # ruleid: authorization-through-sdk
    access.check_can_modify_access_levels_for_object(obj)
    # ruleid: authorization-through-sdk
    access.check_can_modify_access_levels_for_ref(ref)
    # ruleid: authorization-through-sdk
    access.get_user_access_level(obj)
    # ruleid: authorization-through-sdk
    access.specific_access_level_for_object(obj)
    # ruleid: authorization-through-sdk
    access.access_level_for_resource("insight")
    # ruleid: authorization-through-sdk
    access.effective_access_level_for_resource("insight")
    # ruleid: authorization-through-sdk
    access.filter_queryset_by_access_level(queryset)
    # ruleid: authorization-through-sdk
    access.filter_and_annotate_file_system_queryset(queryset)
    # ruleid: authorization-through-sdk
    access.allowed_object_ids("insight")
    # ruleid: authorization-through-sdk
    access.denied_object_ids("insight")
    # ruleid: authorization-through-sdk
    access.bulk_object_access_levels(objects)
    # ruleid: authorization-through-sdk
    access.is_organization_admin
    # ruleid: authorization-through-sdk
    view.user_permissions.team(team).effective_membership_level
    # ruleid: authorization-through-sdk
    access.blocked_resource_ids_by_scope
    # ruleid: authorization-through-sdk
    access.allowlisted_resource_ids_by_scope
    # ruleid: authorization-through-sdk
    access.blocked_resources
    # ruleid: authorization-through-sdk
    membership.level >= OrganizationMembership.Level.ADMIN
    # ruleid: authorization-through-sdk
    OrganizationMembership.Level.MEMBER <= membership.level
    # ruleid: authorization-through-sdk
    membership.level in [OrganizationMembership.Level.ADMIN, OrganizationMembership.Level.OWNER]
    # ruleid: authorization-through-sdk
    membership.level >= Membership.Level.ADMIN


def sdk_authorization(resource, subject):
    # ok: authorization-through-sdk
    authorization.check(resource=resource, action=Action.EDIT, subject=subject)
    # ok: authorization-through-sdk
    authorization.permissions(resource=resource, subject=subject)
    # ok: authorization-through-sdk
    authorization.list_objects(resource=resource, action=Action.VIEW, subject=subject)
    # ok: authorization-through-sdk
    membership = OrganizationMembership(level=OrganizationMembership.Level.MEMBER)
    # ok: authorization-through-sdk
    level = OrganizationMembership.Level.ADMIN
    # ok: authorization-through-sdk
    resource.id == other.id
    # ok: authorization-through-sdk
    access.has_project_access()
    return membership, level
