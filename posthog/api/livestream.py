from typing import cast
from uuid import UUID

import jwt
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.hogql.property_access_types import RestrictedProperty

from posthog.auth import refuse_blocked_account
from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.models import OrganizationMembership, PropertyDefinition, Team, User
from posthog.models.activity_logging.utils import ActivityCredentialMixin
from posthog.models.group_type_mapping import get_group_types_for_team
from posthog.permissions import ActiveOrganizationPermission, VerifiedDomainEnforcementPermission
from posthog.user_permissions import UserPermissions

from products.access_control.backend.property_access_control import (
    get_restricted_properties_with_group_type_index_for_team,
)


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


class LivestreamAuthorizationSerializer(serializers.Serializer):
    restricted_event_properties = serializers.ListField(
        child=serializers.CharField(),
        help_text="Event property names the livestream service must remove before streaming to this user.",
    )
    restricted_person_properties = serializers.ListField(
        child=serializers.CharField(),
        help_text="Person property names the livestream service must remove from $set and $set_once.",
    )
    restricted_group_properties = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        help_text="Group property names to remove from $group_set, keyed by the group type name $group_type carries.",
    )


@extend_schema(exclude=True)
class LivestreamAuthorizationView(APIView):
    authentication_classes = [LivestreamAuthentication]
    permission_classes = [IsAuthenticated, LivestreamOrganizationPermission, LivestreamVerifiedDomainPermission]

    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        team = cast(Team, request.auth)
        level = UserPermissions(user).team(team).effective_membership_level
        if level is None or level < OrganizationMembership.Level.MEMBER:
            raise PermissionDenied("Live stream access is no longer available.")
        if "application/json" not in request.headers.get("Accept", ""):
            # A livestream service that predates the restriction payload treats anything but 204 as an outage.
            return Response(status=204, headers={"Cache-Control": "no-store"})
        restricted = get_restricted_properties_with_group_type_index_for_team(user=user, team=team)
        payload = LivestreamAuthorizationSerializer(
            {
                "restricted_event_properties": sorted(
                    p.name for p in restricted if p.property_type == PropertyDefinition.Type.EVENT
                ),
                "restricted_person_properties": sorted(
                    p.name for p in restricted if p.property_type == PropertyDefinition.Type.PERSON
                ),
                "restricted_group_properties": self._restricted_group_properties_by_type_name(team, restricted),
            }
        ).data
        return Response(payload, headers={"Cache-Control": "no-store"})

    @staticmethod
    def _restricted_group_properties_by_type_name(
        team: Team, restricted: set[RestrictedProperty]
    ) -> dict[str, list[str]]:
        # Rules carry the group type index; a $groupidentify event carries the group type name.
        by_index: dict[int, list[str]] = {}
        for p in restricted:
            if p.property_type == PropertyDefinition.Type.GROUP and p.group_type_index is not None:
                by_index.setdefault(p.group_type_index, []).append(p.name)
        if not by_index:
            return {}
        return {
            mapping["group_type"]: sorted(by_index[mapping["group_type_index"]])
            for mapping in get_group_types_for_team(team.id, caller_tag="livestream_authorize")
            if mapping["group_type_index"] in by_index
        }
