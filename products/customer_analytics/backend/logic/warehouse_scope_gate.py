from typing import Any

from products.access_control.backend.facade.user_access_control import UserAccessControl, model_to_resource
from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
from products.authorization.backend.presentation.querysets import filter_queryset
from products.authorization.backend.presentation.resources import resource_for_object

_OBJECT_ACTIONS = {"viewer": Action.VIEW, "editor": Action.EDIT}

# Custom-property responses can include metadata from these resources. Token scopes must apply even
# though the endpoint itself is authorized as an account resource.
_SCOPE_GATED_RESOURCES = frozenset({"external_data_source", "warehouse_view", "hog_flow"})


class ScopeGatedAccessControl:
    """Wraps ``UserAccessControl`` so cross-resource reads require the matching token scope.

    Custom-property sources and workflow references resolve through object access checks and queryset
    filtering. Applying token scopes here keeps those secondary resources from leaking through an
    account-scoped endpoint. Session auth and ``*`` tokens keep the wrapped access-control behavior.
    """

    def __init__(self, inner: UserAccessControl, token_scopes: list[str]) -> None:
        self._inner = inner
        self._token_scopes = token_scopes

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def check_access_level_for_object(self, obj: Any, required_level: Any, *args: Any, **kwargs: Any) -> bool:
        scope = model_to_resource(obj)
        if not self.allows_scope(scope, required_level):
            return False
        if scope not in _SCOPE_GATED_RESOURCES or required_level not in _OBJECT_ACTIONS or args or kwargs:
            return self._inner.check_access_level_for_object(obj, required_level, *args, **kwargs)
        return authorization.check(
            resource=resource_for_object(obj, team=self._inner.team),
            action=_OBJECT_ACTIONS[required_level],
            subject=Subject(user_id=self._inner.user.pk),
        )

    def filter_queryset_by_access_level(self, queryset: Any, *args: Any, **kwargs: Any) -> Any:
        resource = kwargs.get("resource") or model_to_resource(queryset.model)
        if not self.allows_scope(resource, "viewer"):
            return queryset.none()
        if (
            resource is None
            or resource not in _SCOPE_GATED_RESOURCES
            or self._inner.team is None
            or args
            or kwargs.keys() - {"resource", "include_all_if_admin"}
        ):
            return self._inner.filter_queryset_by_access_level(queryset, *args, **kwargs)
        return filter_queryset(
            queryset,
            resource=Resource(type=ResourceType(resource), project_id=self._inner.team.id),
            subject=Subject(user_id=self._inner.user.pk),
            include_all_if_admin=kwargs.get("include_all_if_admin", False),
        )

    def allows_scope(self, resource: str | None, required_level: str) -> bool:
        scopes = self._token_scopes
        if "*" in scopes or resource not in _SCOPE_GATED_RESOURCES:
            return True
        if f"{resource}:write" in scopes:
            return True
        return required_level == "viewer" and f"{resource}:read" in scopes
