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

import base64
import secrets
import binascii
from urllib.parse import unquote, urlencode

from django.core.cache import cache

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema
from oauth2_provider.models import AbstractApplication
from oauth2_provider.oauth2_validators import OAuth2Validator
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.oauth import OAuthApplication
from posthog.rate_limit import IPThrottle

from .cimd import (
    CIMDFetchError,
    CIMDValidationError,
    enforce_cimd_creation_throttle,
    get_application_by_client_id,
    get_or_create_cimd_application,
    is_cimd_client_id,
)

logger = structlog.get_logger(__name__)

# RFC 9126 mandates the `urn:ietf:params:oauth:request_uri:` namespace for the
# returned reference so the authorization endpoint can tell a pushed request
# apart from a `request_uri` pointing at a remote request object (RFC 9101).
PAR_REQUEST_URI_PREFIX = "urn:ietf:params:oauth:request_uri:"

# The reference is short-lived: a client pushes then immediately redirects the
# browser. RFC 9126 recommends a short lifetime; the authorization code + PKCE
# remain the real anti-replay guards, so this only bounds how long the pushed
# parameters sit in the cache. Long enough to comfortably cover a login/SSO/2FA
# round trip, since `/oauth/authorize/` is `login_required` and the reference is
# only read once the user lands back on it.
PAR_REQUEST_URI_LIFETIME_SECONDS = 60 * 5

# Parameters we do NOT persist from a pushed request: client-authentication
# parameters (they authenticate the push, they are not part of the authorization
# request) and a nested request_uri (rejected outright, see below). Everything
# else the client sends is stored verbatim and replayed at the authorization
# endpoint, so any authorize parameter — including PostHog's access-level hints —
# round-trips through PAR unchanged.
PAR_EXCLUDED_PARAMS = frozenset({"client_secret", "request_uri"})

# Upper bound on the stored (urlencoded) parameter set. A full advertised scope
# list plus redirect_uri/state/PKCE is only a few KB, so 8 KiB fits every real
# request while keeping the expanded /oauth/authorize/ URL the authorization
# endpoint redirects to below the ~8 KiB request-line/header limits common in
# proxies and servers — and bounding how much a public client can write into the
# shared cache per push.
PAR_MAX_STORED_BYTES = 8 * 1024


def _cache_key(reference: str) -> str:
    return f"oauth_par:{reference}"


def consume_pushed_authorization_request(request_uri: str, client_id: str | None) -> dict | None:
    """Return the stored parameters for a pushed `request_uri`, or None if it is
    unknown/expired, or the authorization request does not carry the client_id
    the reference was issued to.

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

    # RFC 9126 §4: a pushed request is bound to the client that pushed it. The
    # authorization request must supply the same client_id, so a reference can
    # be replayed neither under a different client nor without identifying one.
    if not client_id or params.get("client_id") != client_id:
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

    # The authorization parameters below are declared to document the contract for
    # generated clients, docs, and MCP consumers. They are stored verbatim from the
    # request body and their values are validated later at /oauth/authorize/, so
    # they stay optional here (a client may push any subset) and carry no per-field
    # length cap — the whole stored set is bounded by PAR_MAX_STORED_BYTES instead
    # (a small cap on `scope` would wrongly reject a full advertised scope list).
    # CIMD (URL-form) client_ids are the metadata URL itself, which the CIMD row
    # allows up to 2048 chars — matching /oauth/authorize/, which imposes no cap —
    # so keep the same ceiling here or a long-but-valid CIMD client_id would 400.
    client_id = serializers.CharField(max_length=2048, help_text="OAuth client identifier issued to the application.")
    client_secret = serializers.CharField(
        required=False,
        max_length=512,
        help_text="Client secret, required only for confidential clients (token_endpoint_auth_method=client_secret_post).",
    )
    request_uri = serializers.CharField(
        required=False,
        max_length=512,
        help_text="Not permitted: a pushed authorization request must not itself contain a request_uri (RFC 9126 §2.1).",
    )
    redirect_uri = serializers.CharField(
        required=False, help_text="Where to send the browser after authorization; must match a registered redirect URI."
    )
    response_type = serializers.CharField(
        required=False, help_text="OAuth response type. Use `code` for the code flow."
    )
    scope = serializers.CharField(required=False, help_text="Space-delimited list of requested OAuth scopes.")
    state = serializers.CharField(
        required=False, help_text="Opaque value echoed back to the client to maintain state / prevent CSRF."
    )
    code_challenge = serializers.CharField(required=False, help_text="PKCE code challenge (RFC 7636).")
    code_challenge_method = serializers.CharField(
        required=False, help_text="PKCE code challenge method, typically `S256`."
    )
    nonce = serializers.CharField(
        required=False, help_text="OpenID Connect nonce binding the ID token to this request."
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
    # A pushed request is form-urlencoded (or JSON) scalar parameters. Excluding
    # MultiPartParser keeps uploaded file objects out of request.data, so no file
    # can slip into the cached payload past the urlencoded-size bound below.
    parser_classes = [FormParser, JSONParser]

    @extend_schema(
        request=PushedAuthorizationRequestSerializer,
        responses={201: PushedAuthorizationResponseSerializer},
        extensions={"x-product": "core"},
    )
    def post(self, request: Request) -> Response:
        # Confidential clients may authenticate with client_secret_basic (creds in
        # the Authorization header) just as they can at /oauth/token/, so fold any
        # Basic credentials into the payload before validating.
        payload = _merge_basic_auth(request)

        serializer = PushedAuthorizationRequestSerializer(data=payload)
        if not serializer.is_valid():
            logger.warning("oauth_par_validation_error", errors=serializer.errors)
            return Response(
                {"error": "invalid_request", "error_description": str(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        # RFC 9126 §2.1: a pushed request must not carry a request_uri itself.
        if data.get("request_uri"):
            logger.warning("oauth_par_rejected_nested_request_uri", client_id=data.get("client_id"))
            return Response(
                {"error": "invalid_request", "error_description": "request_uri is not allowed in a pushed request."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        client_id = data["client_id"]

        # First-use CIMD provisioning triggers a synchronous outbound metadata
        # fetch, so gate it on the same per-IP throttles /oauth/authorize/ uses
        # before that work runs — otherwise this public endpoint could amplify
        # cheap pushes into unbounded provisioning at the looser PAR IP limit.
        if throttled := enforce_cimd_creation_throttle(request, self, client_id):
            logger.warning("oauth_par_cimd_throttled", client_id=client_id)
            return throttled

        application = _resolve_application(client_id)
        if application is None:
            logger.warning("oauth_par_invalid_client", client_id=client_id)
            return Response(
                {"error": "invalid_client", "error_description": "Invalid client_id."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Client authentication (RFC 9126 §2). Confidential clients must present a
        # valid secret; public clients (PKCE) authenticate with client_id alone.
        if application.client_type == AbstractApplication.CLIENT_CONFIDENTIAL:
            if not _client_secret_valid(application, data.get("client_secret")):
                logger.warning("oauth_par_invalid_client_secret", client_id=client_id)
                return Response(
                    {"error": "invalid_client", "error_description": "Invalid client credentials."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

        # Store every submitted authorization parameter verbatim (minus the
        # client-auth and nested-request_uri params) so the request replays at
        # /oauth/authorize/ exactly as pushed. client_id is required, so it is
        # always present for the binding check in consume_pushed_authorization_request.
        stored = {key: value for key, value in payload.items() if key not in PAR_EXCLUDED_PARAMS}
        stored["client_id"] = client_id

        if len(urlencode(stored)) > PAR_MAX_STORED_BYTES:
            logger.warning("oauth_par_request_too_large", client_id=client_id)
            return Response(
                {"error": "invalid_request", "error_description": "The authorization request is too large."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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


def _resolve_application(client_id: str) -> OAuthApplication | None:
    """Resolve the pushing client, provisioning first-use CIMD clients exactly as
    the authorization endpoint does.

    A CIMD (URL-form) client_id has no pre-registration — first use is what fetches
    the metadata and creates the row — so mirror `OAuthValidator.validate_client_id`
    and lazily provision here. Otherwise a CIMD client's first PAR push would 401
    where `/oauth/authorize/` succeeds, breaking exactly the many-scope client
    population PAR is meant to help.
    """
    if is_cimd_client_id(client_id):
        try:
            return get_or_create_cimd_application(client_id)
        except (CIMDFetchError, CIMDValidationError) as e:
            logger.warning("oauth_par_cimd_resolution_failed", client_id=client_id, error=str(e))
            return None
    try:
        return get_application_by_client_id(client_id)
    except OAuthApplication.DoesNotExist:
        return None


def _merge_basic_auth(request: Request) -> dict:
    """Return the request body with any HTTP Basic client credentials folded in.

    Confidential clients using `client_secret_basic` send `client_id:client_secret`
    in the Authorization header rather than the form body. Body values take
    precedence; Basic only fills in what the body omits.
    """
    # dict(request.data) would yield lists per key for a QueryDict; .items() keeps
    # the last scalar value per key, matching how the fields are read downstream.
    payload = dict(request.data.items())
    basic_client_id, basic_client_secret = _parse_basic_auth_header(request)
    if basic_client_id and not payload.get("client_id"):
        payload["client_id"] = basic_client_id
    if basic_client_secret and not payload.get("client_secret"):
        payload["client_secret"] = basic_client_secret
    return payload


def _parse_basic_auth_header(request: Request) -> tuple[str | None, str | None]:
    """Extract `client_id`/`client_secret` from an HTTP Basic Authorization header
    (RFC 6749 §2.3.1). Returns (None, None) when absent or malformed."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith("Basic "):
        return None, None
    try:
        decoded = base64.b64decode(header[len("Basic ") :].strip()).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None, None
    client_id, _, client_secret = decoded.partition(":")
    return (unquote(client_id) or None), (unquote(client_secret) or None)


def _client_secret_valid(application: OAuthApplication, provided_secret: str | None) -> bool:
    if not provided_secret:
        return False
    # Reuse django-oauth-toolkit's secret comparison so hashed and legacy
    # plaintext secrets are handled identically to the token endpoint.
    return OAuth2Validator()._check_secret(provided_secret, application.client_secret)
