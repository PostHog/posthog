import uuid
from urllib.parse import quote, urlencode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseRedirect

import structlog
from rest_framework import decorators, exceptions, permissions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.organization import OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration

from ee.vercel.client import VercelAPIClient

logger = structlog.get_logger(__name__)

CONNECT_SESSION_TIMEOUT = 600  # 10 minutes


def _get_connect_cache_key(session_key: str) -> str:
    return f"vercel_connect:{session_key}"


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
        next_url = request.query_params.get("next", "")
        configuration_id = request.query_params.get("configurationId", "")

        if not code:
            raise exceptions.ValidationError("Missing code parameter")

        client_id = getattr(settings, "VERCEL_CLIENT_INTEGRATION_ID", "")
        client_secret = getattr(settings, "VERCEL_CLIENT_INTEGRATION_SECRET", "")
        redirect_uri = f"{settings.SITE_URL}/connect/vercel/callback"

        if not client_id or not client_secret:
            logger.error("Vercel connect: missing configuration", integration="vercel")
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
                "Vercel connect: OAuth token exchange failed",
                error=token_response.error,
                error_description=token_response.error_description,
                integration="vercel",
            )
            raise exceptions.AuthenticationFailed(f"Vercel authentication failed: {token_response.error}")

        session_key = str(uuid.uuid4())
        cache.set(
            _get_connect_cache_key(session_key),
            {
                "access_token": token_response.access_token,
                "token_type": token_response.token_type,
                "installation_id": token_response.installation_id,
                "user_id": token_response.user_id,
                "team_id": token_response.team_id,
                "configuration_id": configuration_id,
                "next_url": next_url,
            },
            timeout=CONNECT_SESSION_TIMEOUT,
        )

        link_params = {"session": session_key}
        if next_url:
            link_params["next"] = next_url

        link_url = f"/connect/vercel/link?{urlencode(link_params)}"

        if not request.user.is_authenticated:
            login_url = f"/login?next={quote(link_url)}"
            return HttpResponseRedirect(redirect_to=login_url)

        return HttpResponseRedirect(redirect_to=link_url)


class VercelConnectLinkSerializer(serializers.Serializer):
    session = serializers.CharField(required=True)
    organization_id = serializers.UUIDField(required=True)


class VercelConnectLinkViewSet(viewsets.GenericViewSet):
    """API endpoint to complete the Vercel connectable account linking."""

    permission_classes = [permissions.IsAuthenticated]

    @decorators.action(detail=False, methods=["post"], url_path="complete")
    def complete(self, request: Request) -> Response:
        serializer = VercelConnectLinkSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(serializer.errors)

        session_key = serializer.validated_data["session"]
        organization_id = serializer.validated_data["organization_id"]

        cached_data = cache.get(_get_connect_cache_key(session_key))
        if not cached_data:
            raise exceptions.ValidationError("Session expired. Please try linking again from Vercel.")

        # Verify the user is a member of the selected org
        try:
            membership = OrganizationMembership.objects.get(
                user=request.user,
                organization_id=organization_id,
            )
        except OrganizationMembership.DoesNotExist:
            raise exceptions.PermissionDenied("You are not a member of this organization.")

        if membership.level < OrganizationMembership.Level.ADMIN:
            raise exceptions.PermissionDenied("You must be an admin or owner to link this organization.")

        organization = membership.organization
        installation_id = cached_data["installation_id"]

        # Check if this org already has a Vercel integration
        existing = OrganizationIntegration.objects.filter(
            organization=organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        ).first()

        if existing:
            raise exceptions.ValidationError(
                "This organization already has a Vercel integration. "
                "Please unlink the existing one first or choose a different organization."
            )

        OrganizationIntegration.objects.create(
            organization=organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=installation_id,
            config={
                "type": "connectable",
                "credentials": {
                    "access_token": cached_data["access_token"],
                    "token_type": cached_data["token_type"],
                },
                "vercel_team_id": cached_data.get("team_id"),
                "vercel_user_id": cached_data["user_id"],
                "configuration_id": cached_data.get("configuration_id"),
                "user_mappings": {
                    cached_data["user_id"]: request.user.pk,
                },
            },
            created_by=request.user,
        )

        # Clean up the session
        cache.delete(_get_connect_cache_key(session_key))

        logger.info(
            "Vercel connectable account linked",
            installation_id=installation_id,
            organization_id=str(organization_id),
            user_id=request.user.pk,
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
        """Returns session data and user's orgs for the frontend to render."""
        session_key = request.query_params.get("session")
        if not session_key:
            raise exceptions.ValidationError("Missing session parameter")

        cached_data = cache.get(_get_connect_cache_key(session_key))
        if not cached_data:
            raise exceptions.ValidationError("Session expired. Please try linking again from Vercel.")

        # Get user's organizations where they're admin or owner
        memberships = OrganizationMembership.objects.filter(
            user=request.user,
            level__gte=OrganizationMembership.Level.ADMIN,
        ).select_related("organization")

        organizations = []
        for m in memberships:
            has_vercel = OrganizationIntegration.objects.filter(
                organization=m.organization,
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            ).exists()

            organizations.append(
                {
                    "id": str(m.organization.id),
                    "name": m.organization.name,
                    "already_linked": has_vercel,
                }
            )

        return Response(
            {
                "next_url": cached_data.get("next_url", ""),
                "organizations": organizations,
            }
        )
