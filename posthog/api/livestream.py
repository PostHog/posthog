import hashlib
from ipaddress import ip_network
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

from posthog.api.livestream_impersonation import LivestreamImpersonation
from posthog.auth import refuse_blocked_account
from posthog.ip_restrictions import get_ip_restrictions_for_principal
from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.models import OrganizationMembership, Team, User
from posthog.models.activity_logging.utils import ActivityCredentialMixin
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.permissions import ActiveOrganizationPermission, VerifiedDomainEnforcementPermission
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose
from posthog.user_permissions import UserPermissions

from products.access_control.backend.property_access_control import (
    get_restricted_properties_with_group_type_index_for_team,
)
from products.event_definitions.backend.models import PropertyDefinition

# Mirrors AnyGroupType in the livestream service.
ANY_GROUP_TYPE = "*"
LIVESTREAM_POLICY_ACCESS = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.LIVESTREAM_AUTHORIZATION, settings_name="LIVESTREAM_AUTHORIZATION_SIGNING_KEYS"
)


class LivestreamAuthentication(ActivityCredentialMixin, BaseAuthentication):
    activity_credential_type = "internal_jwt"
    impersonated_by_id: int | None = None

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
            impersonated_by_id = claims.get("impersonated_by_id")
            if impersonated_by_id is not None and (
                type(impersonated_by_id) is not int
                or not User.objects.filter(id=impersonated_by_id, is_active=True, is_staff=True).exists()
                or not LivestreamImpersonation.verify(claims, claims["user_id"], impersonated_by_id)
            ):
                raise ValueError("Invalid impersonation identity")
            user = User.objects.get(id=claims["user_id"], is_active=True)
            team = Team.objects.select_related("organization").get(
                id=claims["team_id"],
                organization_id=UUID(str(claims["organization_id"])),
                api_token=claims["api_token"],
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError, User.DoesNotExist, Team.DoesNotExist):
            raise AuthenticationFailed("Invalid live stream token.")
        # The livestream service re-checks every stream here, so a blocked account's 7-day token stops working.
        self.impersonated_by_id = impersonated_by_id
        refuse_blocked_account(request, user, call_site="livestream", impersonated=impersonated_by_id is not None)
        self.record_activity_actor(user, impersonated_by_id=impersonated_by_id)
        return user, team


class LivestreamOrganizationPermission(ActiveOrganizationPermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return self._admits(cast(Team, request.auth).organization)


class LivestreamVerifiedDomainPermission(VerifiedDomainEnforcementPermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return self._admits(request, cast(Team, request.auth).organization)


class LivestreamAuthorizationSerializer(serializers.Serializer):
    ip_restrictions = serializers.ListField(
        child=serializers.ListField(child=serializers.CharField()),
        help_text="Organization IP policies the streaming service must each enforce against the viewer IP.",
    )
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
        help_text="Group property names to remove from $group_set, keyed by the group type name $group_type carries, or by * for every type.",
    )


@extend_schema(exclude=True)
class LivestreamAuthorizationView(APIView):
    authentication_classes = [LivestreamAuthentication]
    permission_classes = [IsAuthenticated, LivestreamOrganizationPermission, LivestreamVerifiedDomainPermission]

    @staticmethod
    def _verify_policy_access(request: Request, team_id: int) -> None:
        token = request.headers.get("X-PostHog-Livestream-Service-Token", "")
        try:
            claims = LIVESTREAM_POLICY_ACCESS.verify(token)
            viewer_hash = hashlib.sha256(request.headers.get("Authorization", "").encode()).hexdigest()
            if (
                type(claims.get("exp")) is not int
                or type(claims.get("team_id")) is not int
                or claims["team_id"] != team_id
                or claims.get("operation") != "read_ip_policy"
                or claims.get("viewer_token_sha256") != viewer_hash
            ):
                raise ValueError("Invalid policy access scope")
        except (jwt.PyJWTError, RuntimeError, ValueError) as error:
            raise PermissionDenied("Live stream policy access requires streaming service authentication.") from error

    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        team = cast(Team, request.auth)
        level = UserPermissions(user).team(team).effective_membership_level
        if level is None or level < OrganizationMembership.Level.MEMBER:
            raise PermissionDenied("Live stream access is no longer available.")
        authenticator = cast(LivestreamAuthentication, request.successful_authenticator)
        ip_restrictions = (
            []
            if authenticator.impersonated_by_id is not None
            else [
                [str(ip_network(rule, strict=False)) for rule in rules]
                for _, rules in get_ip_restrictions_for_principal(user)
            ]
        )
        if ip_restrictions and request.headers.get("X-PostHog-Livestream-IP-Policy") != "1":
            raise PermissionDenied("The streaming service must support organization IP restrictions.")
        if ip_restrictions:
            self._verify_policy_access(request, team.id)
        if "application/json" not in request.headers.get("Accept", ""):
            # A livestream service that predates the restriction payload treats anything but 204 as an outage.
            return Response(status=204, headers={"Cache-Control": "no-store"})
        restricted = get_restricted_properties_with_group_type_index_for_team(user=user, team=team)
        payload = LivestreamAuthorizationSerializer(
            {
                "ip_restrictions": ip_restrictions,
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
        by_name = {
            mapping["group_type"]: sorted(by_index.pop(mapping["group_type_index"]))
            for mapping in get_group_types_for_project(team.project_id, caller_tag="livestream_authorize")
            if mapping["group_type_index"] in by_index
        }
        if by_index:
            # The lookup failed or the type is gone, so these names cannot be attributed to a type.
            # Fail closed: the service hides them on every group type rather than on none.
            by_name[ANY_GROUP_TYPE] = sorted({name for names in by_index.values() for name in names})
        return by_name
