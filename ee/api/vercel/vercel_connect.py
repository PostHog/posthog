from typing import cast
from urllib.parse import quote, urlencode, urlparse

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect

import structlog
from cryptography.fernet import InvalidToken
from rest_framework import decorators, exceptions, permissions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.team import Team
from posthog.models.user import User

from ee.api.vercel.crypto import decrypt_payload, encrypt_payload, mark_token_used
from ee.vercel.client import APIError, VercelAPIClient

logger = structlog.get_logger(__name__)

ALLOWED_REDIRECT_DOMAINS = {
    "vercel.com",
    "www.vercel.com",
}

CONNECT_SESSION_TIMEOUT = 600  # 10 minutes
CONNECT_SALT = "vercel_connect"


def _sign_connect_session(data: dict) -> str:
    return encrypt_payload(data, salt=CONNECT_SALT, jti=True)


def _load_connect_session(token: str) -> dict:
    try:
        return decrypt_payload(token, salt=CONNECT_SALT, ttl=CONNECT_SESSION_TIMEOUT)
    except InvalidToken:
        raise signing.BadSignature("Invalid or expired token")


def _mark_token_used(jti: str) -> bool:
    return mark_token_used(jti, ttl=CONNECT_SESSION_TIMEOUT)


def _validate_next_url(url: str) -> str:
    """Validate and sanitize the next_url to prevent open redirects."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme not in ("https", "http"):
        return ""
    if not parsed.hostname or parsed.hostname not in ALLOWED_REDIRECT_DOMAINS:
        return ""
    return url


def _is_installation_orphaned(integration: OrganizationIntegration) -> bool:
    """Return True if Vercel no longer recognises this installation (401/403/404).

    Returns False when Vercel confirms the installation is active, or when
    we cannot reach Vercel (network/5xx) -- in that ambiguous case we keep
    the existing integration to avoid accidental deletion.
    """
    access_token = integration.sensitive_config.get("credentials", {}).get("access_token")
    if not access_token:
        return False

    installation_id = integration.integration_id
    if not installation_id:
        return False

    client = VercelAPIClient(bearer_token=access_token)
    try:
        return not client.check_installation_active(installation_id)
    except APIError:
        return False


class VercelConnectCallbackViewSet(viewsets.GenericViewSet):
    """Handles the Vercel connectable account (Link Existing Account) flow.

    When a user clicks "Link Existing Account" in the Vercel Marketplace,
    Vercel opens a popup to our Redirect URL with an OAuth code.
    We exchange the code for an access token and then link the user's
    existing PostHog org to the Vercel installation.
    """

    permission_classes = [permissions.AllowAny]

    @decorators.action(detail=False, methods=["get"], url_path="callback")
    def callback(self, request: Request) -> HttpResponse:
        code = request.query_params.get("code")
        next_url = _validate_next_url(request.query_params.get("next", ""))
        configuration_id = request.query_params.get("configurationId", "")

        if not code:
            raise exceptions.ValidationError("Missing code parameter")

        client_id = getattr(settings, "VERCEL_CLIENT_INTEGRATION_ID", "")
        client_secret = getattr(settings, "VERCEL_CLIENT_INTEGRATION_SECRET", "")
        redirect_uri = f"{settings.SITE_URL}/connect/vercel/callback"

        if not client_id or not client_secret:
            logger.error("vercel_connect_missing_configuration", integration="vercel")
            capture_exception(Exception("Vercel connect: missing client configuration"))
            raise exceptions.APIException("Vercel integration not configured")

        client = VercelAPIClient(bearer_token=None)
        token_response = client.oauth_token_exchange(
            code=code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )

        if token_response.error:
            logger.error(
                "vercel_connect_token_exchange_failed",
                error=token_response.error,
                error_description=token_response.error_description,
                integration="vercel",
            )
            raise exceptions.AuthenticationFailed("Vercel authentication failed")

        session_token = _sign_connect_session(
            {
                "access_token": token_response.access_token,
                "token_type": token_response.token_type,
                "installation_id": token_response.installation_id,
                "user_id": token_response.user_id,
                "team_id": token_response.team_id,
                "configuration_id": configuration_id,
                "next_url": next_url,
            }
        )

        link_url = f"/connect/vercel/link?{urlencode({'session': session_token})}"

        if not request.user.is_authenticated:
            login_url = f"/login?next={quote(link_url)}"
            return HttpResponseRedirect(redirect_to=login_url)
        else:
            return HttpResponseRedirect(redirect_to=link_url)


class VercelConnectLinkSerializer(serializers.Serializer):
    session = serializers.CharField(required=True)
    organization_id = serializers.UUIDField(required=True)
    team_id = serializers.IntegerField(required=True)


class VercelConnectLinkViewSet(viewsets.GenericViewSet):
    """API endpoint to complete the Vercel connectable account linking."""

    permission_classes = [permissions.IsAuthenticated]

    @decorators.action(detail=False, methods=["post"], url_path="complete")
    def complete(self, request: Request) -> Response:
        serializer = VercelConnectLinkSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(serializer.errors)

        user = cast(User, request.user)
        session_key = serializer.validated_data["session"]
        organization_id = serializer.validated_data["organization_id"]
        team_id = serializer.validated_data["team_id"]

        try:
            cached_data = _load_connect_session(session_key)
        except signing.BadSignature:
            raise exceptions.ValidationError("Session expired or invalid. Please try linking again from Vercel.")

        jti = cached_data.get("jti")
        if not jti or not _mark_token_used(jti):
            raise exceptions.ValidationError("Session already used. Please try linking again from Vercel.")

        try:
            membership = OrganizationMembership.objects.get(
                user=user,
                organization_id=organization_id,
            )
        except OrganizationMembership.DoesNotExist:
            raise exceptions.PermissionDenied("You are not a member of this organization.")

        if membership.level < OrganizationMembership.Level.ADMIN:
            raise exceptions.PermissionDenied("You must be an admin or owner to link this organization.")

        organization = membership.organization
        installation_id = cached_data["installation_id"]

        existing = OrganizationIntegration.objects.filter(
            organization=organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        ).first()

        if existing:
            if _is_installation_orphaned(existing):
                logger.info(
                    "vercel_connect_deleting_orphaned_integration",
                    old_installation_id=existing.integration_id,
                    organization_id=str(organization_id),
                    integration="vercel",
                )
                existing.delete()
            else:
                raise exceptions.ValidationError(
                    "This organization already has a Vercel integration. "
                    "Please unlink the existing one first or choose a different organization."
                )

        try:
            team = Team.objects.get(pk=team_id, organization=organization)
        except Team.DoesNotExist:
            raise exceptions.ValidationError("The selected project does not belong to this organization.")

        if Integration.objects.filter(team=team, kind=Integration.IntegrationKind.VERCEL).exists():
            raise exceptions.ValidationError("This project already has a Vercel integration.")

        with transaction.atomic():
            OrganizationIntegration.objects.create(
                organization=organization,
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
                integration_id=installation_id,
                config={
                    "type": "connectable",
                    "vercel_team_id": cached_data.get("team_id"),
                    "vercel_user_id": cached_data["user_id"],
                    "configuration_id": cached_data.get("configuration_id"),
                    "user_mappings": {
                        cached_data["user_id"]: user.pk,
                    },
                },
                sensitive_config={
                    "credentials": {
                        "access_token": cached_data["access_token"],
                        "token_type": cached_data["token_type"],
                    },
                },
                created_by=user,
            )

            resource = Integration.objects.create(
                team=team,
                kind=Integration.IntegrationKind.VERCEL,
                integration_id=str(team.pk),
                config={"type": "connectable"},
                created_by=user,
            )

        from ee.vercel.integration import VercelIntegration

        client = VercelAPIClient(bearer_token=cached_data["access_token"])
        import_result = client.import_resource(
            integration_config_id=installation_id,
            resource_id=str(resource.pk),
            product_id="posthog",
            name=team.name,
            secrets=VercelIntegration._build_secrets(team),
        )
        if not import_result.success:
            logger.error(
                "Failed to import resource to Vercel",
                error=import_result.error,
                installation_id=installation_id,
                resource_id=str(resource.pk),
                integration="vercel",
            )

        VercelIntegration.bulk_sync_feature_flags_to_vercel(team)

        logger.info(
            "Vercel connectable account linked",
            installation_id=installation_id,
            organization_id=str(organization_id),
            team_id=team_id,
            user_id=user.pk,
            integration="vercel",
        )

        return Response(
            {
                "status": "linked",
                "organization_id": str(organization_id),
                "organization_name": organization.name,
                "next_url": cached_data.get("next_url", ""),
            },
            status=201,
        )

    @decorators.action(detail=False, methods=["get"], url_path="session")
    def session_info(self, request: Request) -> Response:
        session_key = request.query_params.get("session")
        if not session_key:
            raise exceptions.ValidationError("Missing session parameter")

        try:
            cached_data = _load_connect_session(session_key)
        except signing.BadSignature:
            raise exceptions.ValidationError("Session expired or invalid. Please try linking again from Vercel.")

        user = cast(User, request.user)
        memberships = OrganizationMembership.objects.filter(
            user=user,
            level__gte=OrganizationMembership.Level.ADMIN,
        ).select_related("organization")

        org_ids = [m.organization_id for m in memberships]
        vercel_integrations = {
            i.organization_id: i
            for i in OrganizationIntegration.objects.filter(
                organization_id__in=org_ids,
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            )
        }

        orphaned_org_ids: set = set()
        for org_id, integration in vercel_integrations.items():
            if _is_installation_orphaned(integration):
                logger.info(
                    "vercel_session_deleting_orphaned_integration",
                    installation_id=integration.integration_id,
                    organization_id=str(org_id),
                    integration="vercel",
                )
                integration.delete()
                orphaned_org_ids.add(org_id)

        teams_by_org: dict = {}
        for team in Team.objects.filter(organization_id__in=org_ids).order_by("name"):
            teams_by_org.setdefault(team.organization_id, []).append(team)

        teams_with_vercel = set(
            Integration.objects.filter(
                team__organization_id__in=org_ids,
                kind=Integration.IntegrationKind.VERCEL,
            ).values_list("team_id", flat=True)
        )

        organizations = [
            {
                "id": str(m.organization.id),
                "name": m.organization.name,
                "already_linked": m.organization_id in vercel_integrations
                and m.organization_id not in orphaned_org_ids,
                "teams": [
                    {
                        "id": t.pk,
                        "name": t.name,
                        "already_linked": t.pk in teams_with_vercel,
                    }
                    for t in teams_by_org.get(m.organization_id, [])
                ],
            }
            for m in memberships
        ]

        return Response(
            {
                "next_url": cached_data.get("next_url", ""),
                "organizations": organizations,
            }
        )
