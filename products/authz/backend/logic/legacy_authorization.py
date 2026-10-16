from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, cast
from uuid import UUID

from posthog.models import OrganizationMembership, Team, User
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.authorization import authorization_roles
from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import AccessControlLevelResource, UserAccessControl
from products.dashboards.backend.facade.authorization import LegacyDashboardAuthorization

if TYPE_CHECKING:
    from products.product_analytics.backend.facade.contracts import AuthorizationInsight

from ..facade.contracts import CheckRequest, Context, ObjectIds, Resource, Subject
from ..facade.enums import Action, ResourceType
from . import authorization, request_context


def dashboard_level(action: Action) -> AccessControlLevelResource:
    if action == Action.VIEW:
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

    def check_insight(self, access: UserAccessControl, action: Action, insight: AuthorizationInsight) -> bool:
        assert access.team is not None
        level = dashboard_level(action)
        ref = ObjectAccessRef(
            resource="insight",
            id=str(insight.id),
            team_id=access.team.id,
            created_by_id=insight.created_by_id,
        )
        if not access.check_access_level_for_ref(ref, level):
            return False
        return (
            level != "editor"
            or not insight.dashboard_ids
            or any(
                self.dashboard_access(access).check(str(dashboard_id), "editor")
                for dashboard_id in insight.dashboard_ids
            )
        )

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
        if resource.id is None:
            if not access.has_project_access:
                return False
            category = cast(APIScopeObject, authorization.resource_category(resource.type).value)
            if action == Action.MANAGE_ACCESS:
                assert access.team is not None
                return access.check_can_modify_access_levels_for_object(
                    access.team
                ) or access.check_access_level_for_resource(category, "manager")
            return access.check_access_level_for_resource(category, level)
        if resource.type == ResourceType.INSIGHT:
            if not access.has_project_access:
                return False
            assert access.team is not None
            from products.product_analytics.backend.facade.api import (  # noqa: PLC0415 -- defer product analytics models
                authorization_insights,
            )

            insight = next(iter(authorization_insights(access.team.id, (int(resource.id),))), None)
            return insight is not None and self.check_insight(access, action, insight)
        return self.dashboard_access(access).check(resource.id, level)

    def list_objects(self, resource: Resource, action: Action, subject: Subject | None, limit: int | None) -> ObjectIds:
        if resource.id is not None or resource.type not in (ResourceType.DASHBOARD, ResourceType.INSIGHT):
            raise ValueError("List resources requires a supported resource type")
        if resource.project_id is None:
            raise ValueError("List resources requires a project")
        if limit is not None and limit < 1:
            raise ValueError("Resource limit must be positive")
        authorization.action_relation(f"{resource.type}:0", action)
        authorization.organization_id(resource)
        user = self.user(subject)
        if user is None:
            return ObjectIds(ids=frozenset(), complete=True)
        access = self.user_access(user, resource)
        if not access.has_project_access:
            return ObjectIds(ids=frozenset(), complete=True)
        if resource.type == ResourceType.DASHBOARD:
            dashboard_ids = self.dashboard_access(access).ids(dashboard_level(action), limit)
            return ObjectIds(ids=dashboard_ids or frozenset(), complete=dashboard_ids is not None)

        assert access.team is not None
        ids: set[str] = set()
        from products.product_analytics.backend.facade.api import (  # noqa: PLC0415 -- defer product analytics models
            authorization_insights,
        )

        insight_ids = authorization_insights(access.team.id)
        for insight in insight_ids:
            if insight.deleted:
                continue
            if self.check_insight(access, action, insight):
                ids.add(str(insight.id))
                if limit is not None and len(ids) > limit:
                    return ObjectIds(ids=frozenset(), complete=False)
        return ObjectIds(ids=frozenset(ids), complete=True)

    def read_object_filter(
        self,
        resource: Resource,
        subject: Subject | None,
        limit: int | None,
        creator_exempt: bool,
        user_access_control: UserAccessControl | None,
    ) -> ObjectIds:
        """Same shape as the OpenFGA list: only objects with a rule of their own can differ from the
        resource level, so those are resolved one by one and the rest follow the resource level."""
        if resource.id is not None or resource.project_id is None:
            raise ValueError("List resources requires a resource category scoped to a project")
        if limit is not None and limit < 1:
            raise ValueError("Resource limit must be positive")
        cap = limit if limit is not None else authorization.MAX_IDS
        level: AccessControlLevelResource = "viewer"
        if user_access_control is not None and subject is not None and subject.user_id == user_access_control.user.pk:
            preloaded_user = user_access_control.user
            if isinstance(preloaded_user, User) and preloaded_user.is_active:
                self.users.setdefault(preloaded_user.id, preloaded_user)
        user = self.user(subject)
        if user is None:
            return ObjectIds(ids=frozenset(), complete=True)
        access = self.adopt(user, resource, user_access_control) or self.user_access(user, resource)

        def build(ids: frozenset[str], *, excluded: bool) -> ObjectIds:
            return ObjectIds(ids=ids, complete=True, excluded=excluded, creator_exempt=creator_exempt)

        if not access.has_project_access:
            return ObjectIds(ids=frozenset(), complete=True)
        if access.is_organization_admin:
            return build(frozenset(), excluded=True)
        scope = cast(APIScopeObject, resource.type.value)
        with_rule = access.object_ids_with_rules(scope)
        if len(with_rule) > cap:
            return ObjectIds(ids=frozenset(), complete=False)
        allowed = {
            id: access.check_access_level_for_ref(
                ObjectAccessRef(resource=scope, id=id, team_id=resource.project_id, created_by_id=None), level
            )
            for id in with_rule
        }
        if access.check_access_level_for_resource(scope, level):
            return build(frozenset(id for id, ok in allowed.items() if not ok), excluded=True)
        return build(frozenset(id for id, ok in allowed.items() if ok), excluded=False)

    def adopt(
        self, user: User, resource: Resource, user_access_control: UserAccessControl | None
    ) -> UserAccessControl | None:
        """Reuse a caller's preloaded access control for its own user and project, so no rule loads twice."""
        if user_access_control is None or user_access_control.team is None or user_access_control.user.pk != user.pk:
            return None
        team = user_access_control.team
        if team.id != authorization.project_id(resource):
            return None
        return self.access.setdefault((user.id, team.id, team.organization_id), user_access_control)


def evaluator() -> LegacyAuthorization:
    evaluators = request_context.legacy_evaluators.get()
    if evaluators is None:
        return LegacyAuthorization()
    if not evaluators:
        evaluators.append(LegacyAuthorization())
    return evaluators[0]


def check(requests: Sequence[CheckRequest], context: Context | None) -> list[bool]:
    authorization.validate_context(context)
    access = evaluator()
    return [access.check(request) for request in requests]


def list_objects(
    resource: Resource,
    action: Action,
    subject: Subject | None,
    context: Context | None,
    limit: int | None,
    creator_exempt: bool = False,
    user_access_control: UserAccessControl | None = None,
) -> ObjectIds:
    authorization.validate_context(context)
    engine = evaluator()
    if action in (Action.VIEW, Action.QUERY):
        return engine.read_object_filter(resource, subject, limit, creator_exempt, user_access_control)
    return engine.list_objects(resource, action, subject, limit)
