"""The access-control entry point for application code.

Callers ask `ProjectAccess` whether a principal can perform an action on a resource. They never
import `UserAccessControl` (the resolver that walks the rules) or the `AccessControl` rows. That
keeps one place for "what does 'edit' require", one place to log decisions, and one seam behind
which the resolver can change or be replaced.

    access_control = ProjectAccess.for_request(request, team)   # viewsets get this as `self.access_control`
    access_control.check("edit", dashboard)                      # object
    access_control.check("create", "dashboard")                  # resource type
    access_control.require("view", insight)                      # raises PermissionDenied
    access_control.decide("edit", dashboard)                     # AccessDecision with provenance
    access_control.filter(Dashboard.objects.filter(team=team), "view")
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, cast

from django.db.models import Model, QuerySet

from rest_framework.exceptions import PermissionDenied

from posthog.constants import AccessControlLevel
from posthog.rbac.user_access_control import (
    RESOURCE_INHERITANCE_MAP,
    ResolvedAccess,
    UserAccessControl,
    access_level_satisfied_for_resource,
    model_to_resource,
    ordered_access_levels,
)
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.contracts import AccessDecision, Action, PropertyAccessLevel
from products.access_control.backend.property_access_control import (
    get_property_access_level,
    get_restricted_property_names,
)

if TYPE_CHECKING:
    from rest_framework.request import Request

    from posthog.models import PropertyDefinition, Team, User


# Rung on the resource's level ladder each action needs, counted from the bottom (0 = "none").
# Clamped to the ladder's top, so on the member ladder (none, member, admin) "edit" means admin,
# and on resources capped at viewer "edit" is never satisfiable.
_ACTION_RUNG: dict[Action, int] = {
    "view": 1,
    "list": 1,
    "edit": 2,
    "create": 2,
    "manage": 3,
}


def required_level_for(resource: APIScopeObject, action: Action) -> AccessControlLevel:
    ladder = ordered_access_levels(resource)
    return ladder[min(_ACTION_RUNG[action], len(ladder) - 1)]


class AccessResolver(Protocol):
    """What the facade needs from whatever resolves rules. `UserAccessControl` is the only
    implementation; a different engine would implement the same four calls."""

    def resolve_object(self, obj: Model) -> ResolvedAccess | None: ...
    def resolve_resource(self, resource: APIScopeObject) -> ResolvedAccess | None: ...
    def filter_queryset(self, queryset: QuerySet, resource: APIScopeObject | None) -> QuerySet: ...
    def preload(self, objects: Sequence[Model]) -> None: ...


class UserAccessControlResolver:
    def __init__(self, user_access_control: UserAccessControl) -> None:
        self.user_access_control = user_access_control

    def resolve_object(self, obj: Model) -> ResolvedAccess | None:
        return self.user_access_control.resolve_object_access(obj)

    def resolve_resource(self, resource: APIScopeObject) -> ResolvedAccess | None:
        return self.user_access_control.access_level_for_resource(resource)

    def filter_queryset(self, queryset: QuerySet, resource: APIScopeObject | None) -> QuerySet:
        return self.user_access_control.filter_queryset_by_access_level(queryset, resource=resource)

    def preload(self, objects: Sequence[Model]) -> None:
        self.user_access_control.preload_object_access_controls(list(objects))


class ProjectAccess:
    """A principal's access within one project. Build one per request (or per task run) and ask
    it many questions; the resolver behind it caches and preloads, so repeated checks are cheap."""

    def __init__(self, *, resolver: AccessResolver | None, user: "User | None", team: "Team | None") -> None:
        self._resolver = resolver
        self._user = user
        self._team = team

    @classmethod
    def for_user(cls, user: "User", team: "Team | None") -> "ProjectAccess":
        return cls(resolver=UserAccessControlResolver(UserAccessControl(user=user, team=team)), user=user, team=team)

    @classmethod
    def for_request(cls, request: "Request", team: "Team | None") -> "ProjectAccess":
        """Authenticated users resolve normally. Any other principal (anonymous, API-key-only,
        sharing token) gets a closed handle until those principals are modelled here; their
        existing permission classes keep enforcing in the meantime."""
        user = request.user
        if getattr(user, "is_authenticated", False) and not getattr(user, "is_anonymous", True):
            return cls.for_user(cast("User", user), team)
        return cls.denied(team)

    @classmethod
    def from_user_access_control(cls, user_access_control: UserAccessControl) -> "ProjectAccess":
        """For code that already holds a warmed resolver and must not build a second one
        (HogQL threads its preloaded instance through the whole schema build)."""
        return cls(
            resolver=UserAccessControlResolver(user_access_control),
            user=user_access_control.user,
            team=user_access_control.team,
        )

    @classmethod
    def denied(cls, team: "Team | None") -> "ProjectAccess":
        return cls(resolver=None, user=None, team=team)

    # --- decisions ---

    def check(self, action: Action, target: Model | APIScopeObject) -> bool:
        return self.decide(action, target).allowed

    def require(self, action: Action, target: Model | APIScopeObject, *, message: str | None = None) -> None:
        if not self.check(action, target):
            raise PermissionDenied(message or self._denied_message(action, target))

    def check_each(self, action: Action, objects: Sequence[Model]) -> list[bool]:
        if self._resolver is not None and objects:
            self._resolver.preload(objects)
        return [self.check(action, obj) for obj in objects]

    def decide(self, action: Action, target: Model | APIScopeObject) -> AccessDecision:
        if isinstance(target, Model):
            return self._decide_object(action, target)
        return self._decide_resource(action, target)

    def _decide_object(self, action: Action, obj: Model) -> AccessDecision:
        resource = model_to_resource(obj)
        object_id = str(getattr(obj, "id", "")) or None
        if resource is None:
            # Models outside the access-control scope list have no rules, matching the resolver's
            # "permissions do not apply" answer for them.
            return AccessDecision(
                allowed=True,
                action=action,
                resource=obj.__class__.__name__.lower(),
                object_id=object_id,
                level=None,
                required_level=None,
                source=None,
                source_subject=None,
            )
        required = required_level_for(resource, action)
        resolved = self._resolver.resolve_object(obj) if self._resolver is not None else None
        return self._decision(action, resource, object_id, required, resolved, comparison_resource=resource)

    def _decide_resource(self, action: Action, resource: APIScopeObject) -> AccessDecision:
        # Inherited resources compare on the parent's ladder, as the resolver's own check does.
        comparison_resource = RESOURCE_INHERITANCE_MAP.get(resource, resource)
        required = required_level_for(comparison_resource, action)
        resolved = self._resolver.resolve_resource(resource) if self._resolver is not None else None
        return self._decision(action, resource, None, required, resolved, comparison_resource=comparison_resource)

    @staticmethod
    def _decision(
        action: Action,
        resource: APIScopeObject,
        object_id: str | None,
        required: AccessControlLevel,
        resolved: ResolvedAccess | None,
        *,
        comparison_resource: APIScopeObject,
    ) -> AccessDecision:
        allowed = resolved is not None and access_level_satisfied_for_resource(
            comparison_resource, resolved.access_level, required
        )
        return AccessDecision(
            allowed=allowed,
            action=action,
            resource=resource,
            object_id=object_id,
            level=resolved.access_level if resolved else None,
            required_level=required,
            source=resolved.source if resolved else None,
            source_subject=resolved.source_subject if resolved else None,
        )

    @staticmethod
    def _denied_message(action: Action, target: Model | APIScopeObject) -> str:
        name = target.__class__.__name__.lower() if isinstance(target, Model) else target
        return f"You don't have permission to {action} this {name}."

    # --- sets ---

    def filter(self, queryset: QuerySet, action: Action = "view") -> QuerySet:
        """Rows the principal may see. Only "view" is supported: the resolver filters on visibility,
        not on a required level, so asking for "edit" here would silently over-include."""
        if action != "view":
            raise ValueError("filter() only supports the 'view' action")
        if self._resolver is None:
            return queryset.none()
        return self._resolver.filter_queryset(queryset, model_to_resource(cast(Model, queryset.model)))

    # --- property access control ---

    def property_access_level(self, property_definition: "PropertyDefinition") -> PropertyAccessLevel:
        return get_property_access_level(property=property_definition, user=self._property_user())

    def restricted_property_names(self, property_type: int) -> set[str]:
        """Names of properties of this type the principal may not read, for stripping from query results."""
        if self._team is None:
            return set()
        return get_restricted_property_names(
            team_id=self._team.id, user=self._property_user(), property_type=property_type
        )

    def _property_user(self) -> "User | None":
        # Property rules key on membership and roles, which synthetic and anonymous principals lack.
        if self._user is not None and getattr(self._user, "is_authenticated", False):
            return self._user
        return None
