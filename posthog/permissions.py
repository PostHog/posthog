from typing import Optional

from django.db.models import Model
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from posthog.models import Organization, OrganizationMembership


class OrganizationMemberPermissions(BasePermission):
    message = "You don't belong to the organization."

    def has_object_permission(self, request: Request, view, object: Optional[Model]) -> bool:
        organization = object if isinstance(object, Organization) else object.organization
        return OrganizationMembership.objects.filter(user=request.user, organization=organization).exists()


class OrganizationAdminWritePermissions(BasePermission):
    message = "Your organization access level is insufficient."

    def has_object_permission(self, request: Request, view, object: Optional[Model]) -> bool:
        if request.method in SAFE_METHODS:
            return True
        organization = object if isinstance(object, Organization) else object.organization
        return (
            OrganizationMembership.objects.get(user=request.user, organization=organization).level
            >= OrganizationMembership.Level.ADMIN
        )


class OrganizationAdminAnyPermissions(BasePermission):
    message = "Your organization access level is insufficient."

    def has_object_permission(self, request: Request, view, object: Optional[Model]) -> bool:
        organization = object if isinstance(object, Organization) else object.organization
        return (
            OrganizationMembership.objects.get(user=request.user, organization=organization).level
            >= OrganizationMembership.Level.ADMIN
        )
