"""A base for settings the requesting user keeps for themselves, under `/api/<route>/@me/`.

Staff may name another user by UUID. A subclass that reads or writes data of the user's current
project must call `check_team_within_credential_organizations`, because `APIScopePermission` skips
the tenant check for `scope_object = "user"`.

The base class carries no docstring: drf-spectacular reads a view's docstring through its MRO, so
one here would become the published description of every subclass's endpoints.
"""

from typing import cast

from django.db.models import QuerySet

from rest_framework import exceptions, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.auth import (
    IDJagAccessTokenAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
)
from posthog.models import User
from posthog.permissions import APIScopePermission
from posthog.rate_limit import UserAuthenticationThrottle


class UserSettingsViewSet(viewsets.GenericViewSet):
    scope_object = "user"
    permission_classes = [IsAuthenticated, APIScopePermission]
    authentication_classes = [
        IDJagAccessTokenAuthentication,
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    throttle_classes = [UserAuthenticationThrottle]
    queryset = User.objects.filter(is_active=True)
    lookup_field = "uuid"

    def get_object(self) -> User:
        lookup_value = self.kwargs[self.lookup_field]
        request_user = cast(User, self.request.user)

        if lookup_value == "@me":
            self.check_object_permissions(self.request, request_user)
            return request_user

        if not request_user.is_staff:
            raise exceptions.PermissionDenied(
                "As a non-staff user you're only allowed to access the `@me` user instance."
            )

        return super().get_object()

    def get_queryset(self) -> QuerySet[User]:
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(id=self.request.user.id)
        return queryset
