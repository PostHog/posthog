import uuid
from typing import cast
from urllib.parse import quote, urlencode, urlparse

from django.conf import settings
from django.core.cache import cache
from django.core.signing import BadSignature
from django.http import HttpResponse, HttpResponseRedirect

import structlog
from rest_framework import decorators, exceptions, permissions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.user import User

from ee.vercel.client import VercelAPIClient

logger = structlog.get_logger(__name__)

ALLOWED_REDIRECT_DOMAINS = {
    "vercel.com",
    "www.vercel.com",
}

CONNECT_SESSION_TIMEOUT = 600  # 10 minutes
CONNECT_COOKIE_NAME = "vercel_connect_session"
CONNECT_COOKIE_SALT = "vercel_connect"


def _get_connect_cache_key(session_key: str) -> str:
    return f"vercel_connect:{session_key}"


def _get_bound_session_key(request: Request) -> str | None:
    """Read the CSRF-binding session key from the signed cookie.

    Uses a signed cookie instead of the Django session because session.flush()
    is called during SSO login and when switching users, which would destroy
    the binding and break the flow for unauthenticated users.
    """
    try:
        return request._request.get_signed_cookie(
            CONNECT_COOKIE_NAME,
            default=None,
            salt=CONNECT_COOKIE_SALT,
            max_age=CONNECT_SESSION_TIMEOUT,
        )
    except BadSignature:
        return None


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

        link_url = f"/connect/vercel/link?{urlencode({'session': session_key})}"

        if not request.user.is_authenticated:
            login_url = f"/login?next={quote(link_url)}"
            response = HttpResponseRedirect(redirect_to=login_url)
        else:
            response = HttpResponseRedirect(redirect_to=link_url)

        # Bind session_key via signed cookie so it survives session.flush() during SSO login.
        response.set_signed_cookie(
            CONNECT_COOKIE_NAME,
            session_key,
            salt=CONNECT_COOKIE_SALT,
            max_age=CONNECT_SESSION_TIMEOUT,
            httponly=True,
            samesite="Lax",
            secure=not settings.DEBUG,
        )
        return response


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

        user = cast(User, request.user)
        session_key = serializer.validated_data["session"]
        organization_id = serializer.validated_data["organization_id"]

        bound_session_key = _get_bound_session_key(request)
        if bound_session_key != session_key:
            raise exceptions.ValidationError("Session mismatch. Please restart the linking flow from Vercel.")

        cached_data = cache.get(_get_connect_cache_key(session_key))
        if not cached_data:
            raise exceptions.ValidationError("Session expired. Please try linking again from Vercel.")

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
                    cached_data["user_id"]: user.pk,
                },
            },
            created_by=user,
        )

        cache.delete(_get_connect_cache_key(session_key))

        logger.info(
            "Vercel connectable account linked",
            installation_id=installation_id,
            organization_id=str(organization_id),
            user_id=user.pk,
            integration="vercel",
        )

        response = Response(
            {
                "status": "linked",
                "organization_id": str(organization_id),
                "organization_name": organization.name,
                "next_url": cached_data.get("next_url", ""),
            },
            status=201,
        )
        response.delete_cookie(CONNECT_COOKIE_NAME)
        return response

    @decorators.action(detail=False, methods=["get"], url_path="session")
    def session_info(self, request: Request) -> Response:
        session_key = request.query_params.get("session")
        if not session_key:
            raise exceptions.ValidationError("Missing session parameter")

        bound_session_key = _get_bound_session_key(request)
        if bound_session_key != session_key:
            raise exceptions.ValidationError("Session mismatch. Please restart the linking flow from Vercel.")

        cached_data = cache.get(_get_connect_cache_key(session_key))
        if not cached_data:
            raise exceptions.ValidationError("Session expired. Please try linking again from Vercel.")

        user = cast(User, request.user)
        memberships = OrganizationMembership.objects.filter(
            user=user,
            level__gte=OrganizationMembership.Level.ADMIN,
        ).select_related("organization")

        org_ids = [m.organization_id for m in memberships]
        orgs_with_vercel = set(
            OrganizationIntegration.objects.filter(
                organization_id__in=org_ids,
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            ).values_list("organization_id", flat=True)
        )

        organizations = [
            {
                "id": str(m.organization.id),
                "name": m.organization.name,
                "already_linked": m.organization_id in orgs_with_vercel,
            }
            for m in memberships
        ]

        return Response(
            {
                "next_url": cached_data.get("next_url", ""),
                "organizations": organizations,
            }
        )
