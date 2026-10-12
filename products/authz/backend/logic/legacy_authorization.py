from collections.abc import Sequence
from uuid import UUID

from posthog.models import OrganizationMembership, Team, User

from products.access_control.backend.facade.authorization import authorization_roles
from products.access_control.backend.facade.user_access_control import AccessControlLevelResource, UserAccessControl
from products.dashboards.backend.facade.authorization import LegacyDashboardAuthorization

from ..facade.contracts import CheckRequest, Context, Resource, ResourceIds, Subject
from ..facade.enums import Action, ResourceType
from . import authorization


def dashboard_level(action: Action) -> AccessControlLevelResource:
    if action in (Action.VIEW, Action.LIST):
        return "viewer"
    if action in (Action.EDIT, Action.DELETE, Action.SHARE, Action.CREATE):
        return "editor"
    if action == Action.MANAGE_ACCESS:
        return "manager"
    raise ValueError("This action is not supported for dashboards")


class LegacyAuthorization:
    def __init__(self) -> None:
        self.users: dict[int, User | None] = {}
        self.access: dict[tuple[int, int | None, UUID], UserAccessControl] = {}
        self.dashboards: dict[tuple[int, int], LegacyDashboardAuthorization] = {}

    def user(self, subject: Subject | None) -> User | None:
        authorization.actor_key(subject)
        assert subject is not None and subject.user_id is not None
        if subject.user_id not in self.users:
            self.users[subject.user_id] = User.objects.filter(id=subject.user_id, is_active=True).first()
        return self.users[subject.user_id]

    def user_access(self, user: User, resource: Resource) -> UserAccessControl:
        org_id = authorization.organization_id(resource)
        team_id = authorization.project_id(resource)
        key = (user.id, team_id, org_id)
        if key not in self.access:
            team = Team.objects.get(id=team_id, organization_id=org_id) if team_id is not None else None
            self.access[key] = UserAccessControl(user, team=team, organization_id=str(org_id))
        return self.access[key]

    def dashboard_access(self, access: UserAccessControl) -> LegacyDashboardAuthorization:
        assert access.team is not None
        key = (access.user.id, access.team.id)
        if key not in self.dashboards:
            self.dashboards[key] = LegacyDashboardAuthorization(access)
        return self.dashboards[key]

    def check(self, request: CheckRequest) -> bool:
        resource, action = request.resource, request.action
        object = authorization.object_key(resource)
        authorization.action_relation(object, action)
        user = self.user(request.subject)
        if user is None:
            return False
        org_id = authorization.organization_id(resource)
        if resource.type in (ResourceType.ORGANIZATION, ResourceType.ROLE):
            membership = OrganizationMembership.objects.filter(organization_id=org_id, user_id=user.id).first()
            if membership is None:
                return False
            if resource.type == ResourceType.ROLE and not any(
                str(role.id) == str(UUID(resource.id or "")) for role in authorization_roles(org_id)
            ):
                return False
            required_level = (
                OrganizationMembership.Level.MEMBER
                if action == Action.VIEW
                else OrganizationMembership.Level.OWNER
                if resource.type == ResourceType.ORGANIZATION and action in (Action.DELETE, Action.MANAGE_OWNERS)
                else OrganizationMembership.Level.ADMIN
            )
            return membership.level >= required_level
        access = self.user_access(user, resource)
        if resource.type == ResourceType.PROJECT:
            assert access.team is not None
            if action == Action.MANAGE_ACCESS:
                return access.has_project_access and access.check_can_modify_access_levels_for_object(access.team)
            return access.has_project_access and access.check_access_level_for_object(
                access.team, "member" if action == Action.VIEW else "admin"
            )
        level = dashboard_level(action)
        if resource.id is not None:
            return self.dashboard_access(access).check(resource.id, level)
        if not access.has_project_access:
            return False
        if action == Action.MANAGE_ACCESS:
            assert access.team is not None
            return access.check_can_modify_access_levels_for_object(
                access.team
            ) or access.check_access_level_for_resource("dashboard", "manager")
        return access.check_access_level_for_resource("dashboard", level)

    def list_resources(
        self, resource: Resource, action: Action, subject: Subject | None, limit: int | None
    ) -> ResourceIds:
        if resource.id is not None or resource.type != ResourceType.DASHBOARD or resource.project_id is None:
            raise ValueError("List resources requires a dashboard category scoped to a project")
        if limit is not None and limit < 1:
            raise ValueError("Resource limit must be positive")
        authorization.action_relation("dashboard:0", action)
        authorization.organization_id(resource)
        user = self.user(subject)
        if user is None:
            return ResourceIds(ids=frozenset(), complete=True)
        access = self.user_access(user, resource)
        ids = self.dashboard_access(access).ids(dashboard_level(action), limit)
        return ResourceIds(ids=ids or frozenset(), complete=ids is not None)


def check(requests: Sequence[CheckRequest], context: Context | None) -> list[bool]:
    authorization.validate_context(context)
    evaluator = LegacyAuthorization()
    return [evaluator.check(request) for request in requests]


def list_resources(
    resource: Resource, action: Action, subject: Subject | None, context: Context | None, limit: int | None
) -> ResourceIds:
    authorization.validate_context(context)
    return LegacyAuthorization().list_resources(resource, action, subject, limit)
