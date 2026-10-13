"""Enforce an authz `ResourceIds` result in a viewset: the list filter and the per-object check.

The result carries the decision. This module only applies it, because only the viewset knows
its model, its id and its creator column.
"""

from typing import Any

from django.db.models import QuerySet

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from posthog.models.access_filter import apply_filter
from posthog.models.team import Team
from posthog.permissions import AccessControlPermission, is_service_auth

from products.authz.backend.facade import api as authz
from products.authz.backend.facade.contracts import Resource, ResourceIds, Subject
from products.authz.backend.facade.enums import Action, ResourceType

LEVEL_ACTION = {"viewer": Action.VIEW, "editor": Action.EDIT, "manager": Action.MANAGE_ACCESS}


class AuthzPermission(AccessControlPermission):
    """`AccessControlPermission` with the object check taken from the view's authz result."""

    def has_object_permission(self, request: Request, view: Any, object: Any) -> bool:
        if is_service_auth(request) or isinstance(object, Team):
            return super().has_object_permission(request, view, object)
        required_level = self.required_access_level(request, view)
        if required_level is None:
            return True
        result = view.authz_ids(LEVEL_ACTION[required_level])
        allowed = result.allows(
            str(object.pk), created_by_user_id=getattr(object, "created_by_id", None), subject_user_id=request.user.pk
        )
        if not allowed:
            self.message = f"You do not have {required_level} access to this resource."
        return allowed


class AuthzViewSetMixin:
    """Decide list rows and object access with one authz filter instead of the legacy access-control rows.

    Put it before `TeamAndOrgViewSetMixin` in the bases, because it overrides two of its hooks. The
    resource-level gate in `AccessControlPermission.has_permission` stays as it is.
    """

    scope_object: str
    team_id: int
    action: str
    request: Any
    user_access_control: Any

    def authz_ids(self, action: Action) -> ResourceIds:
        return authz.list_resources(
            resource=Resource(type=ResourceType(self.scope_object), project_id=self.team_id),
            action=action,
            subject=Subject(user_id=self.request.user.pk),
            creator_exempt=True,
            user_access_control=self.user_access_control,
        )

    def get_permissions(self) -> list[BasePermission]:
        permissions: list[BasePermission] = super().get_permissions()  # type: ignore[misc]
        return [
            AuthzPermission() if type(permission) is AccessControlPermission else permission
            for permission in permissions
        ]

    def _filter_queryset_by_access_level(self, queryset: QuerySet) -> QuerySet:
        # Service credentials are gated by API scope and project membership, as in the legacy filter.
        if self.action != "list" or is_service_auth(self.request):
            return queryset
        return apply_filter(queryset, self.authz_ids(Action.LIST), subject_user_id=self.request.user.pk)
