from typing import cast

from rest_framework import exceptions
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User


class IsOrganizationAdminOrOwner(BasePermission):
    message = "Your organization access level is insufficient."

    def has_permission(self, request: Request, view: APIView) -> bool:
        organization = getattr(view, "organization", None)
        if organization is None:
            raise exceptions.NotFound("Organization not found.")
        try:
            membership = OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization)
        except OrganizationMembership.DoesNotExist:
            raise exceptions.NotFound("Organization not found.")
        return membership.level >= OrganizationMembership.Level.ADMIN
