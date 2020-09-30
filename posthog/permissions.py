from typing import Optional

from django.db.models import Model
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from posthog.models import OrganizationMembership, organization


class OrganizationMemberPermissions(BasePermission):
    message = "You don't belong to the organization."

    def has_object_permission(self, request: Request, view, object: Optional[Model]) -> bool:
        return object.organization in request.user.organizations


class OrganizationAdminWritePermissions(BasePermission):
    message = "Your organization access level is insufficient."

    def has_object_permission(self, request: Request, view, object: Optional[Model]) -> bool:
        if request.method in self.SAFE_METHODS:
            return True
        return (
            OrganizationMembership.get(user=request.user, organization=object.organization).level
            >= OrganizationMembership.Level.ADMIN
        )


class OrganizationAdminAnyPermissions(BasePermission):
    message = "Your organization access level is insufficient."

    def has_object_permission(self, request: Request, view, object: Optional[Model]) -> bool:
        return (
            OrganizationMembership.get(user=request.user, organization=object.organization).level
            >= OrganizationMembership.Level.ADMIN
        )
