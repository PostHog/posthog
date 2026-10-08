from typing import cast
from uuid import UUID

import jwt
from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import refuse_blocked_account
from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.models import OrganizationMembership, Team, User
from posthog.models.activity_logging.utils import ActivityCredentialMixin
from posthog.permissions import ActiveOrganizationPermission, VerifiedDomainEnforcementPermission
from posthog.user_permissions import UserPermissions


class LivestreamAuthentication(ActivityCredentialMixin, BaseAuthentication):
    activity_credential_type = "internal_jwt"

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"

    def authenticate(self, request: Request) -> tuple[User, Team] | None:
        authorization = get_authorization_header(request).split()
        if not authorization:
            return None
        if len(authorization) != 2 or authorization[0].lower() != b"bearer":
            raise AuthenticationFailed("Invalid live stream token.")
        try:
            claims = decode_jwt(authorization[1].decode(), PosthogJwtAudience.LIVESTREAM)
            if type(claims["user_id"]) is not int or type(claims["team_id"]) is not int:
                raise ValueError("Invalid token identity")
            if not isinstance(claims["api_token"], str) or not claims["api_token"]:
                raise ValueError("Invalid project token")
            user = User.objects.get(id=claims["user_id"], is_active=True)
            team = Team.objects.select_related("organization").get(
                id=claims["team_id"],
                organization_id=UUID(str(claims["organization_id"])),
                api_token=claims["api_token"],
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError, User.DoesNotExist, Team.DoesNotExist):
            raise AuthenticationFailed("Invalid live stream token.")
        # The livestream service re-checks every stream here, so a blocked account's 7-day token stops working.
        refuse_blocked_account(request, user, call_site="livestream", impersonated=False)
        self.record_activity_actor(user)
        return user, team


class LivestreamOrganizationPermission(ActiveOrganizationPermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return self._admits(cast(Team, request.auth).organization)


class LivestreamVerifiedDomainPermission(VerifiedDomainEnforcementPermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return self._admits(request, cast(Team, request.auth).organization)


@extend_schema(exclude=True)
class LivestreamAuthorizationView(APIView):
    authentication_classes = [LivestreamAuthentication]
    permission_classes = [IsAuthenticated, LivestreamOrganizationPermission, LivestreamVerifiedDomainPermission]

    def get(self, request: Request) -> Response:
        level = UserPermissions(cast(User, request.user)).team(cast(Team, request.auth)).effective_membership_level
        if level is None or level < OrganizationMembership.Level.MEMBER:
            raise PermissionDenied("Live stream access is no longer available.")
        return Response(status=204, headers={"Cache-Control": "no-store"})
