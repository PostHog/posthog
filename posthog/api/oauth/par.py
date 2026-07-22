"""
OAuth 2.0 Pushed Authorization Requests (RFC 9126).

Lets a client POST its authorization parameters up front and receive a short,
opaque `request_uri` in return. The client then starts the browser flow with
only `client_id` and `request_uri` in the query string, so the authorization
URL stays small no matter how many scopes are requested. This is the standard
remedy for authorization URLs that grow too long to copy/paste once every scope
is enumerated in the `scope` query parameter.

The pushed parameters are held in the cache under the opaque reference and
rehydrated by the authorization endpoint (see `OAuthAuthorizationView.get`),
which then validates them exactly as it would a normal query-string request.
"""

import secrets

from django.core.cache import cache

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema
from oauth2_provider.models import AbstractApplication
from oauth2_provider.oauth2_validators import OAuth2Validator
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.oauth import OAuthApplication
from posthog.rate_limit import IPThrottle

from .cimd import get_application_by_client_id

logger = structlog.get_logger(__name__)

# RFC 9126 mandates the `urn:ietf:params:oauth:request_uri:` namespace for the
# returned reference so the authorization endpoint can tell a pushed request
# apart from a `request_uri` pointing at a remote request object (RFC 9101).
PAR_REQUEST_URI_PREFIX = "urn:ietf:params:oauth:request_uri:"

# The reference is short-lived: a client pushes then immediately redirects the
# browser. RFC 9126 recommends a short lifetime; the authorization code + PKCE
# remain the real anti-replay guards, so this only bounds how long the pushed
# parameters sit in the cache.
PAR_REQUEST_URI_LIFETIME_SECONDS = 90

# Authorization-request parameters we persist from a pushed request. This mirrors
# every parameter the authorization endpoint reads (directly or via oauthlib).
# Client-authentication parameters (`client_secret`) are deliberately excluded —
# they authenticate the push, they are not part of the authorization request.
PAR_STORED_PARAMS = (
    "client_id",
    "redirect_uri",
    "response_type",
    "scope",
    "state",
    "code_challenge",
    "code_challenge_method",
    "nonce",
    "claims",
    "resource",
    "prompt",
    "approval_prompt",
)


def _cache_key(reference: str) -> str:
    return f"oauth_par:{reference}"


def consume_pushed_authorization_request(request_uri: str, client_id: str | None) -> dict | None:
    """Return the stored parameters for a pushed `request_uri`, or None if it is
    unknown/expired or bound to a different client.

    The reference is intentionally not deleted on read: the browser may reload
    the consent screen (an idempotent GET that mints nothing), and the short TTL
    already bounds reuse. The single-use guarantee that matters — the one on the
    authorization code — is enforced downstream at the token endpoint.
    """
    if not request_uri.startswith(PAR_REQUEST_URI_PREFIX):
        return None

    reference = request_uri[len(PAR_REQUEST_URI_PREFIX) :]
    params = cache.get(_cache_key(reference))
    if not isinstance(params, dict):
        return None

    # A pushed request is bound to the client that pushed it. The authorization
    # request must carry the same client_id, so a reference cannot be replayed
    # under a different client.
    if client_id and params.get("client_id") != client_id:
        return None

    return params


class PARBurstThrottle(IPThrottle):
    """Rate limit pushed authorization requests by IP - burst limit."""

    scope = "oauth_par_burst"
    rate = "60/minute"


class PARSustainedThrottle(IPThrottle):
    """Rate limit pushed authorization requests by IP - sustained limit."""

    scope = "oauth_par_sustained"
    rate = "1000/hour"


class PushedAuthorizationRequestSerializer(serializers.Serializer):
    """Validates an RFC 9126 pushed authorization request. Fields mirror the
    query parameters of a normal OAuth authorization request."""

    client_id = serializers.CharField(help_text="OAuth client identifier issued to the application.")
    client_secret = serializers.CharField(
        required=False,
        help_text="Client secret, required only for confidential clients (token_endpoint_auth_method=client_secret_post).",
    )
    redirect_uri = serializers.CharField(
        required=False, help_text="Redirect URI the authorization response is sent to."
    )
    response_type = serializers.CharField(required=False, help_text="OAuth response type; must be 'code'.")
    scope = serializers.CharField(
        required=False, allow_blank=True, help_text="Space-delimited OAuth scopes being requested."
    )
    state = serializers.CharField(
        required=False, help_text="Opaque value used by the client to maintain state between request and callback."
    )
    code_challenge = serializers.CharField(required=False, help_text="PKCE code challenge (RFC 7636).")
    code_challenge_method = serializers.CharField(required=False, help_text="PKCE code challenge method; 'S256'.")
    nonce = serializers.CharField(required=False, help_text="OpenID Connect nonce.")
    claims = serializers.CharField(required=False, help_text="OpenID Connect claims request parameter (JSON string).")
    resource = serializers.CharField(
        required=False, help_text="Resource indicator (RFC 8707) identifying the protected resource."
    )
    prompt = serializers.CharField(required=False, help_text="OpenID Connect prompt parameter, e.g. 'login'.")
    approval_prompt = serializers.CharField(
        required=False, help_text="Whether to force the consent screen ('force') or allow auto-approval ('auto')."
    )
    request_uri = serializers.CharField(
        required=False,
        help_text="Not permitted: a pushed authorization request must not itself contain a request_uri (RFC 9126 §2.1).",
    )


class PushedAuthorizationResponseSerializer(serializers.Serializer):
    """RFC 9126 §2.2 success response."""

    request_uri = serializers.CharField(help_text="Opaque reference to pass as the `request_uri` authorize parameter.")
    expires_in = serializers.IntegerField(help_text="Seconds until the request_uri expires.")


class OAuthPushedAuthorizationRequestView(APIView):
    """
    OAuth 2.0 Pushed Authorization Request endpoint (RFC 9126).

    Accepts the parameters of an authorization request as a direct POST,
    authenticates the client, and returns a `request_uri` the client uses to
    start the browser authorization flow with a short query string.
    """

    permission_classes: list = []
    authentication_classes: list = []
    throttle_classes = [PARBurstThrottle, PARSustainedThrottle]

    @extend_schema(
        request=PushedAuthorizationRequestSerializer,
        responses={201: PushedAuthorizationResponseSerializer},
        extensions={"x-product": "core"},
    )
    def post(self, request: Request) -> Response:
        serializer = PushedAuthorizationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "invalid_request", "error_description": str(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        # RFC 9126 §2.1: a pushed request must not carry a request_uri itself.
        if data.get("request_uri"):
            return Response(
                {"error": "invalid_request", "error_description": "request_uri is not allowed in a pushed request."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        client_id = data["client_id"]
        try:
            application = get_application_by_client_id(client_id)
        except OAuthApplication.DoesNotExist:
            return Response(
                {"error": "invalid_client", "error_description": "Invalid client_id."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Client authentication (RFC 9126 §2). Confidential clients must present a
        # valid secret; public clients (PKCE) authenticate with client_id alone.
        if application.client_type == AbstractApplication.CLIENT_CONFIDENTIAL:
            if not _client_secret_valid(application, data.get("client_secret")):
                return Response(
                    {"error": "invalid_client", "error_description": "Invalid client credentials."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

        stored = {key: data[key] for key in PAR_STORED_PARAMS if data.get(key) is not None}
        # client_id is required, so it is always present; keep it explicit for the
        # binding check in consume_pushed_authorization_request.
        stored["client_id"] = client_id

        reference = secrets.token_urlsafe(32)
        cache.set(_cache_key(reference), stored, timeout=PAR_REQUEST_URI_LIFETIME_SECONDS)

        posthoganalytics.capture(
            distinct_id=str(application.client_id),
            event="oauth_pushed_authorization_request",
            properties={
                "client_name": application.name,
                "app_id": str(application.pk),
                "is_first_party": application.is_first_party,
            },
        )

        return Response(
            {
                "request_uri": f"{PAR_REQUEST_URI_PREFIX}{reference}",
                "expires_in": PAR_REQUEST_URI_LIFETIME_SECONDS,
            },
            status=status.HTTP_201_CREATED,
        )


def _client_secret_valid(application: OAuthApplication, provided_secret: str | None) -> bool:
    if not provided_secret:
        return False
    # Reuse django-oauth-toolkit's secret comparison so hashed and legacy
    # plaintext secrets are handled identically to the token endpoint.
    return OAuth2Validator()._check_secret(provided_secret, application.client_secret)
