"""RFC 8628 device authorization grant.

A client without a browser, such as hog, gets a device code and a user code from
`/oauth/device-authorization`. The person opens the approval page and enters or confirms the user code.
Then the person selects a project and approves. The client polls `/oauth/token` with the device code.
It gets a token for that project, with the scopes that the client asked for at the start.

django-oauth-toolkit supplies the grant, but its token path is not safe:
- It takes the scopes from the poll request.
- It does not check expiry.
- It does not bind the device code to the client that started the grant.
- It lets a client use an approved code again.
The token path in this module prevents each of these.
"""

import json
import base64
import hashlib
import secrets
from datetime import timedelta
from typing import Any, cast
from urllib.parse import unquote_plus

from django.conf import settings
from django.core.cache import cache
from django.db import models, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema
from oauth2_provider.models import AbstractApplication
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.views.device import DeviceAuthorizationView
from oauthlib.common import Request as OAuthlibRequest
from oauthlib.oauth2 import DeviceApplicationServer
from oauthlib.oauth2.rfc6749 import errors as rfc6749_errors
from oauthlib.oauth2.rfc8628 import errors as rfc8628_errors
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from posthog.accessible_teams import AccessibleTeams, CredentialScopeDenied
from posthog.api.oauth.client_assertion import resolve_client_assertion
from posthog.auth import SessionAuthentication
from posthog.helpers.oauth_pending_connection import (
    PendingOAuthConnection,
    PendingOAuthFlow,
    clear_pending_oauth_connection_cookie,
)
from posthog.helpers.two_factor_session import missing_two_factor_step
from posthog.helpers.verified_domain_enforcement import VERIFIED_DOMAIN_REQUIRED_ERROR
from posthog.models import Team, User
from posthog.models.oauth import OAuthApplication, OAuthDeviceGrant, live_oauth_access_tokens, live_oauth_refresh_tokens
from posthog.models.organization_domain import OrganizationDomain
from posthog.rate_limit import IPThrottle
from posthog.scopes import clamp_scopes_to_ceiling, resolve_requested_scopes, scopes_not_covered

logger = structlog.get_logger(__name__)

DEVICE_CODE_GRANT_TYPE = AbstractApplication.GRANT_DEVICE_CODE
# The token endpoint's answers while the person hasn't decided yet (RFC 8628 section 3.5).
DEVICE_POLL_WAITING_ERRORS = frozenset({"authorization_pending", "slow_down"})

# RFC 8628 section 6.1: consonants only, so a code never spells a word or mixes up look-alikes.
USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"
USER_CODE_LENGTH = 8
USER_CODE_INPUT_MAX_LENGTH = 20

# A poll that arrives this much earlier than the interval still counts as on time, so network
# jitter doesn't earn a well-behaved client a slow_down.
POLL_INTERVAL_TOLERANCE = timedelta(seconds=1)
# RFC 8628 section 3.5: each `slow_down` adds 5 seconds to the interval the client must keep.
SLOW_DOWN_INTERVAL_STEP = 5
MAX_POLL_INTERVAL = 60

# `OAuthApplication.allows_grant_type` refuses an unverified device client. This says why.
UNVERIFIED_CLIENT_DESCRIPTION = (
    "PostHog hasn't verified this app. Device login only works for apps PostHog has verified, "
    "which are PostHog's own apps."
)


def generate_user_code() -> str:
    code = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(USER_CODE_LENGTH))
    return f"{code[:4]}-{code[4:]}"


def normalize_user_code(raw: str) -> str:
    """Return the stored form of a code that a person typed: upper case, with the dash in its usual position."""
    code = "".join(character for character in raw.upper() if character.isalnum())
    return f"{code[:4]}-{code[4:]}" if len(code) == USER_CODE_LENGTH else code


def verification_uri() -> str:
    return f"{settings.SITE_URL}/device"


def resolve_device_scopes(raw_scope: str | None, application: OAuthApplication) -> list[str]:
    """Return the scopes that a device grant asks the person to approve.

    The device grant does not accept `*`, which is different from `/authorize`.
    The result always includes the application's required scopes. The approval page never lets the
    person remove them.
    """
    requested = resolve_requested_scopes((raw_scope or "").split(), application.ceiling_scopes)
    return sorted({*requested, *(scope for scope in application.required_scopes if ":" in scope)})


def _device_grant(request: OAuthlibRequest) -> OAuthDeviceGrant:
    grant = getattr(request, "device_grant", None)
    if not isinstance(grant, OAuthDeviceGrant):
        raise rfc6749_errors.InvalidGrantError(request=request)
    return grant


def load_device_grant(request: OAuthlibRequest) -> None:
    """oauthlib pre-token hook: copy the approved user and project onto the token request.

    The token view locks the grant first, and checks that it is approved and not expired.
    `_get_scoped_teams_and_organizations` reads the project from these request attributes.
    """
    device_code = getattr(request, "device_code", None)
    grant = (
        OAuthDeviceGrant.objects.select_related("user")
        .filter(device_code=device_code, status=OAuthDeviceGrant.AUTHORIZED)
        .first()
    )
    if grant is None or grant.user is None:
        raise rfc6749_errors.InvalidGrantError(request=request)
    request.device_grant = grant
    request.user = grant.user
    request.scoped_teams = list(grant.scoped_teams or [])
    request.scoped_organizations = []


def apply_device_grant(request: OAuthlibRequest) -> None:
    """oauthlib post-token hook. It runs after the generic scope check.

    Only the client that started the device grant can redeem it.
    The token gets the scopes that the person approved, clamped to the client's current ceiling.
    The `scope` parameter of the poll request has no effect.
    """
    grant = _device_grant(request)
    if request.client.client_id != grant.client_id:
        raise rfc6749_errors.InvalidGrantError(request=request)
    request.scopes = clamp_scopes_to_ceiling(set((grant.scope or "").split()), request.client.ceiling_scopes)


def token_server_kwargs() -> dict[str, Any]:
    """Return the server kwargs for the token endpoint. They make the device code grant run the hooks above."""
    return {
        **oauth2_settings.server_kwargs,
        "pre_token": [load_device_grant],
        "post_token": [apply_device_grant],
    }


def _error_response(error: rfc6749_errors.OAuth2Error) -> JsonResponse:
    return JsonResponse(json.loads(error.json), status=error.status_code)


def _presented_client_id(request: HttpRequest) -> str | None:
    """Return the client_id of a request. It can be in the body, in a client assertion, or in HTTP Basic auth.

    Basic auth form-encodes the client_id (RFC 6749 section 2.3.1), so the colons in a CIMD URL arrive escaped.
    This function decodes it in the same way as the toolkit.
    """
    if client_id := request.POST.get("client_id"):
        return client_id
    assertion = resolve_client_assertion(
        request.POST.get("client_assertion", ""), request.POST.get("client_assertion_type", ""), ""
    )
    if assertion is not None:
        return assertion.client_id
    scheme, _, credentials = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        return unquote_plus(base64.b64decode(credentials).decode().partition(":")[0]) or None
    except (ValueError, UnicodeDecodeError):
        return None


def _pending_poll_error(grant: OAuthDeviceGrant) -> rfc6749_errors.OAuth2Error:
    now = timezone.now()
    too_early = grant.last_checked and now - grant.last_checked < timedelta(seconds=grant.interval) - (
        POLL_INTERVAL_TOLERANCE
    )
    # `last_checked` is auto_now, so saving it records this poll.
    if not too_early:
        grant.save(update_fields=["last_checked"])
        return rfc8628_errors.AuthorizationPendingError()
    grant.interval = min(grant.interval + SLOW_DOWN_INTERVAL_STEP, MAX_POLL_INTERVAL)
    grant.save(update_fields=["last_checked", "interval"])
    return rfc8628_errors.SlowDownError()


def device_token_response(create_token_response: Any, request: HttpRequest, device_code: str) -> HttpResponse:
    """Return the token endpoint's response to a device code poll.

    The grant row stays locked until the token exists and the grant is deleted.
    Thus two polls cannot redeem one approval.
    An app-wide session revoke deletes device grants first. Thus it either waits for this token and
    revokes it, or deletes the grant before the token exists.
    """
    # The token endpoint needs no login, so this caps the row locks and writes one device code can
    # cause at one per second, however fast its holder polls. The client is part of the key, so
    # another client polling the same code can't use up the real client's second.
    poller = f"{_presented_client_id(request) or ''}\n{device_code}"
    poll_key = f"oauth_device_poll:{hashlib.sha256(poller.encode()).hexdigest()}"
    if not cache.add(poll_key, True, timeout=1):
        return _error_response(rfc8628_errors.SlowDownError())
    with transaction.atomic():
        # Filtered on the presented client too, so a poll that names another client locks nothing,
        # and varying the client can't get past the per-second limit to pile up locks on the row.
        # A poll by another client neither learns the status nor moves `last_checked`. The
        # post-token hook checks the authenticated client again.
        grant = (
            OAuthDeviceGrant.objects.select_for_update()
            .filter(device_code=device_code, client_id=_presented_client_id(request) or "")
            .first()
        )
        if grant is None:
            return _error_response(rfc6749_errors.InvalidGrantError(description="The device code is not valid."))
        if grant.status in (OAuthDeviceGrant.AUTHORIZATION_PENDING, OAuthDeviceGrant.AUTHORIZED) and (
            timezone.now() >= grant.expires
        ):
            grant.status = OAuthDeviceGrant.EXPIRED
            grant.save(update_fields=["status"])
        if grant.status == OAuthDeviceGrant.EXPIRED:
            return _error_response(rfc8628_errors.ExpiredTokenError())
        if grant.status == OAuthDeviceGrant.DENIED:
            return _error_response(rfc8628_errors.AccessDenied())
        if grant.status == OAuthDeviceGrant.AUTHORIZATION_PENDING:
            return _error_response(_pending_poll_error(grant))

        _url, headers, body, status_code = create_token_response(request)
        if status_code == 200:
            grant.delete()

    response = HttpResponse(content=body, status=status_code, content_type="application/json")
    for key, value in headers.items():
        response[key] = value
    return response


@method_decorator(csrf_exempt, name="dispatch")
class OAuthDeviceAuthorizationView(DeviceAuthorizationView):
    """`POST /oauth/device-authorization`: start a device grant (RFC 8628 section 3.1).

    oauthlib checks the client and creates the codes. This view adds checks that oauthlib does not do:
    - The client must be registered for the device grant.
    - The requested scopes are clamped to the client's ceiling and stored.
    - The scopes in `required_scopes` must be among those clamped scopes.
    Thus the token can only get the scopes that the person saw and approved.
    """

    @classmethod
    def get_server(cls) -> DeviceApplicationServer:
        return DeviceApplicationServer(
            cls.get_validator_class()(),
            verification_uri=verification_uri(),
            verification_uri_complete=f"{verification_uri()}?code={{user_code}}",
            interval=oauth2_settings.DEVICE_FLOW_INTERVAL,
            user_code_generator=generate_user_code,
        )

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Late import: the views module imports this one for the token endpoint.
        from posthog.api.oauth.views import cimd_creation_throttled  # noqa: PLC0415

        # This endpoint needs no login and writes a row per call, so it is limited per IP. A CIMD
        # client_id also makes PostHog fetch a document, so new CIMD clients get the same per-IP
        # limit as on /oauth/authorize.
        # The IP throttles read only `request.META`, which a Django request has too.
        drf_request = cast(Request, request)
        if not all(throttle().allow_request(drf_request, self) for throttle in DEVICE_AUTHORIZATION_THROTTLE_CLASSES):
            return JsonResponse(
                {"error": "slow_down", "error_description": "Too many login attempts. Try again in a minute."},
                status=429,
            )
        if request.GET:
            # oauthlib also reads parameters from the query string. A client_id there would skip the
            # CIMD creation limit below, which reads only the body and the Authorization header.
            return _error_response(
                rfc6749_errors.InvalidRequestError(description="URL query parameters are not allowed.")
            )
        client_id = _presented_client_id(request) or ""
        if client_id and "client_id" not in request.POST:
            # RFC 8628 section 3.1 needs no client_id in the body from a client that authenticates,
            # but oauthlib reads it only from there.
            post = request.POST.copy()
            post["client_id"] = client_id
            request.POST = post  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        if cimd_creation_throttled(request, self, client_id):
            return JsonResponse(
                {"error": "invalid_client", "error_description": "Too many new client registrations. Try again later."},
                status=400,
            )
        headers, body, status_code = self.create_device_authorization_response(request)
        if status_code != 200:
            return JsonResponse(data=json.loads(body), status=status_code, headers=headers)

        response = cast(dict[str, Any], body)
        application = OAuthApplication.objects.filter(client_id=client_id).first()
        if (
            application is not None
            and application.authorization_grant_type == AbstractApplication.GRANT_DEVICE_CODE
            and not application.is_verified
        ):
            return _error_response(rfc6749_errors.UnauthorizedClientError(description=UNVERIFIED_CLIENT_DESCRIPTION))
        if application is None or not application.allows_grant_type(AbstractApplication.GRANT_DEVICE_CODE):
            return _error_response(
                rfc6749_errors.UnauthorizedClientError(description="This client can't use the device grant.")
            )

        scopes = resolve_device_scopes(request.POST.get("scope"), application)
        # Checked after the ceiling clamp, so a client can't lock a scope the approval page won't show.
        required = sorted(set(request.POST.get("required_scopes", "").split()))
        if not_requested := [scope for scope in required if scope not in scopes]:
            return _error_response(
                rfc6749_errors.InvalidScopeError(
                    description="These required scopes aren't among the requested scopes this client can get: "
                    + " ".join(not_requested)
                )
            )

        OAuthDeviceGrant.objects.create(
            client_id=application.client_id,
            device_code=response["device_code"],
            user_code=response["user_code"],
            scope=" ".join(scopes),
            required_scope=" ".join(required) or None,
            interval=response["interval"],
            expires=timezone.now() + timedelta(seconds=response["expires_in"]),
        )
        return JsonResponse(data=response, status=status_code, headers={**headers, "Cache-Control": "no-store"})


class OAuthDeviceAuthorizationBurstThrottle(IPThrottle):
    scope = "oauth_device_authorization_burst"
    rate = "5/minute"


class OAuthDeviceAuthorizationSustainedThrottle(IPThrottle):
    scope = "oauth_device_authorization_sustained"
    rate = "30/hour"


DEVICE_AUTHORIZATION_THROTTLE_CLASSES = (
    OAuthDeviceAuthorizationBurstThrottle,
    OAuthDeviceAuthorizationSustainedThrottle,
)


class OAuthDeviceCodeBurstThrottle(UserRateThrottle):
    # A person enters a code once or twice per login, so anything faster is guessing.
    scope = "oauth_device_code_burst"
    rate = "10/minute"


class OAuthDeviceCodeSustainedThrottle(UserRateThrottle):
    scope = "oauth_device_code_sustained"
    rate = "50/hour"


class DeviceUserCodeSerializer(serializers.Serializer):
    user_code = serializers.CharField(
        max_length=USER_CODE_INPUT_MAX_LENGTH,
        help_text="The code the device shows, as the person typed it. Case and dashes don't matter.",
    )


class DeviceApprovalSerializer(DeviceUserCodeSerializer):
    project_id = serializers.IntegerField(help_text="The project the token is scoped to.")
    scopes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=False,
        help_text="The requested scopes the person kept. Leave it out to grant every requested scope. It must "
        "include every scope in `required_scopes`, and nothing outside the requested scopes.",
    )


class GrantedScopesSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(
        allow_null=True,
        help_text="The project these scopes work in. Null when the connection is not limited to projects.",
    )
    organization_id = serializers.CharField(
        allow_null=True,
        help_text="The organization these scopes work in, for a connection limited to organizations. Null when "
        "the connection is not limited to organizations.",
    )
    scopes = serializers.ListField(child=serializers.CharField(), help_text="The scopes granted in the project.")


class DeviceGrantDetailsSerializer(serializers.Serializer):
    user_code = serializers.CharField(help_text="The code, in the form the device shows it.")
    client_id = serializers.CharField(help_text="The client that started the device grant.")
    client_name = serializers.CharField(help_text="The client's display name.")
    logo_uri = serializers.CharField(allow_null=True, help_text="The client's logo, if it declared one.")
    is_verified = serializers.BooleanField(help_text="Whether PostHog has verified the client.")
    scopes = serializers.ListField(
        child=serializers.CharField(), help_text="The scopes the token will carry if the person approves."
    )
    required_scopes = serializers.ListField(
        child=serializers.CharField(),
        help_text="The requested scopes the person can't leave out: the client's required scopes, the scopes the "
        "client marked as required when it started the grant, such as the new scopes of a step-up, and identity "
        "scopes such as `openid`.",
    )
    granted_scopes = GrantedScopesSerializer(
        many=True,
        help_text="The scopes the person already gave this client, per project. A step-up in a project asks for "
        "these plus new ones.",
    )
    expires_at = serializers.DateTimeField(help_text="When the code expires.")


class DeviceDecision(models.TextChoices):
    AUTHORIZED = OAuthDeviceGrant.AUTHORIZED, "Authorized"
    DENIED = OAuthDeviceGrant.DENIED, "Denied"


class DeviceDecisionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=DeviceDecision.choices, help_text="The device grant's status after the decision."
    )


def _required_scopes(grant: OAuthDeviceGrant, application: OAuthApplication) -> list[str]:
    """Return the requested scopes that approval always keeps: the client's required scopes, the scopes
    the client marked as required for this grant, and the identity scopes, which grant no access to data."""
    required = {*application.required_scopes, *(grant.required_scope or "").split()}
    return [scope for scope in (grant.scope or "").split() if scope in required or ":" not in scope]


def _invalid_code() -> Response:
    return Response(
        {
            "error": "invalid_code",
            "error_description": "This code is wrong, expired or already used. Check the code your terminal shows, or start the login again.",
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def _invalid_scope(description: str) -> Response:
    return Response({"error": "invalid_scope", "error_description": description}, status=status.HTTP_400_BAD_REQUEST)


def _unverified_client() -> Response:
    return Response(
        {"error": "unverified_client", "error_description": UNVERIFIED_CLIENT_DESCRIPTION},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _granted_scopes(user: User, application: OAuthApplication) -> list[dict[str, object]]:
    """The scopes the user's standing connections to this client carry, per project, counted the way
    the Connected applications page counts them. A scope granted in one project grants nothing in
    another, so a step-up only hides scopes the chosen project already has."""
    rows = [
        *live_oauth_access_tokens(user)
        .filter(application=application)
        .values_list("scope", "scoped_teams", "scoped_organizations"),
        *live_oauth_refresh_tokens(user)
        .filter(application=application)
        .values_list("access_token__scope", "access_token__scoped_teams", "access_token__scoped_organizations"),
    ]
    # Keyed by (project, organization). A connection limited to organizations counts only in them, and
    # only a connection limited to neither counts everywhere.
    granted: dict[tuple[int | None, str | None], set[str]] = {}
    for scope, scoped_teams, scoped_organizations in rows:
        if scoped_teams:
            places: list[tuple[int | None, str | None]] = [(project_id, None) for project_id in scoped_teams]
        elif scoped_organizations:
            places = [(None, organization_id) for organization_id in scoped_organizations]
        else:
            places = [(None, None)]
        for place in places:
            granted.setdefault(place, set()).update((scope or "").split())
    return [
        {"project_id": project_id, "organization_id": organization_id, "scopes": sorted(scopes)}
        for (project_id, organization_id), scopes in sorted(
            granted.items(), key=lambda item: (item[0][0] or 0, item[0][1] or "")
        )
    ]


def _capture(request: Request, event: str, grant: OAuthDeviceGrant, **properties: object) -> None:
    """Device approval events share the `oauth_*` client properties, so they line up with
    `oauth_token_issued` for the same client."""
    # Late import: the views module imports this one for the token endpoint.
    from posthog.api.oauth.views import _oauth_app_event_properties  # noqa: PLC0415

    application = OAuthApplication.objects.filter(client_id=grant.client_id).first()
    posthoganalytics.capture(
        distinct_id=str(cast(User, request.user).distinct_id),
        event=event,
        properties={**(_oauth_app_event_properties(application) if application else {}), **properties},
    )


def _pending_grant(user_code: str, *, lock: bool = False) -> OAuthDeviceGrant | None:
    queryset = OAuthDeviceGrant.objects.filter(
        user_code=normalize_user_code(user_code),
        status=OAuthDeviceGrant.AUTHORIZATION_PENDING,
        expires__gt=timezone.now(),
    )
    if lock:
        queryset = queryset.select_for_update()
    return queryset.order_by("-created").first()


class SignedOutDeviceCodeThrottle(IPThrottle):
    # The login redirect names the app only for a live code, so it tells a visitor without a
    # session whether a code exists. This limits how fast one address can guess codes that way.
    scope = "oauth_device_signed_out_code"
    rate = "10/minute"


def pending_device_connection(request: HttpRequest) -> PendingOAuthConnection | None:
    """Public metadata of the app that started the device grant a signed-out visitor's code names."""
    user_code = request.GET.get("code", "")
    if not user_code or len(user_code) > USER_CODE_INPUT_MAX_LENGTH:
        return None
    # The IP throttle reads only `request.META`, which a Django request has too.
    if not SignedOutDeviceCodeThrottle().allow_request(cast(Request, request), cast(APIView, None)):
        logger.info("oauth_device_signed_out_code_throttled")
        return None
    grant = _pending_grant(user_code)
    if grant is None:
        return None
    application = (
        OAuthApplication.objects.only("name", "client_id", "logo_uri")
        .filter(client_id=grant.client_id, is_verified=True)
        .first()
    )
    if application is None:
        return None
    return PendingOAuthConnection(
        client_name=application.name,
        client_id=application.client_id,
        logo_uri=application.logo_uri or None,
        flow=PendingOAuthFlow.DEVICE,
    )


# `x-internal` keeps the approval page's API out of the public docs, but in the codegen build that
# gives the page its generated client.
@extend_schema(tags=["oauth"], extensions={"x-product": "core", "x-internal": True})
class OAuthDeviceViewSet(viewsets.ViewSet):
    """The approval page's API for device grants. Session only: a token can never approve one."""

    _ip_restrictions_use_view_scope = True
    include_in_api_docs = True
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [OAuthDeviceCodeBurstThrottle, OAuthDeviceCodeSustainedThrottle]

    @extend_schema(request=DeviceUserCodeSerializer, responses={200: DeviceGrantDetailsSerializer})
    @action(methods=["POST"], detail=False)
    def lookup(self, request: Request) -> Response:
        """Show what a device code asks for, so the person can check it before approving."""
        serializer = DeviceUserCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grant = _pending_grant(serializer.validated_data["user_code"])
        application = grant and OAuthApplication.objects.filter(client_id=grant.client_id).first()
        if grant is None or application is None:
            return _invalid_code()
        # Staff can withdraw a verification while a grant is pending.
        if not application.is_verified:
            return _unverified_client()
        # pinned: analytics event names, which dashboards depend on
        _capture(request, "oauth_device_authorization_viewed", grant)
        return Response(
            DeviceGrantDetailsSerializer(
                {
                    "user_code": grant.user_code,
                    "client_id": application.client_id,
                    "client_name": application.name,
                    "logo_uri": application.logo_uri or None,
                    "is_verified": application.is_verified,
                    "scopes": (grant.scope or "").split(),
                    "required_scopes": _required_scopes(grant, application),
                    "granted_scopes": _granted_scopes(cast(User, request.user), application),
                    "expires_at": grant.expires,
                }
            ).data
        )

    @extend_schema(request=DeviceApprovalSerializer, responses={200: DeviceDecisionSerializer})
    @action(methods=["POST"], detail=False)
    def approve(self, request: Request) -> Response:
        """Approve a device grant for one project. The token gets the requested scopes the person kept."""
        # Late import: the views module imports this one for the token endpoint.
        from posthog.api.oauth.views import _gateway_blocklist_block, _impersonator_id_for_request  # noqa: PLC0415

        serializer = DeviceApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # An impersonated session must not hand a client a long-lived token in the user's name.
        if _impersonator_id_for_request(request) is not None:
            return Response(
                {"error": "access_denied", "error_description": "You can't approve a device while impersonating."},
                status=status.HTTP_403_FORBIDDEN,
            )

        team = Team.objects.select_related("organization").filter(id=serializer.validated_data["project_id"]).first()
        if team is None:
            return Response(
                {"error": "invalid_project", "error_description": "Project not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            AccessibleTeams.for_request(request, [team.id])
        except CredentialScopeDenied:
            return Response(
                {"error": "access_denied", "error_description": "You don't have access to this project."},
                status=status.HTTP_403_FORBIDDEN,
            )
        # Session auth checks the 2FA policy of the current organization only, and the token never
        # meets a 2FA check later, so the policy of the project's organization is checked here.
        if missing_two_factor_step(request._request, cast(User, request.user), organization=team.organization):
            return Response(
                {
                    "error": "two_factor_required",
                    "error_description": "This project's organization requires two-factor authentication. Set it up, then try again.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        # The same gap for the verified-domain policy: session auth checks the current organization only.
        if OrganizationDomain.objects.is_email_blocked_by_domain_enforcement(
            cast(User, request.user).email, team.organization
        ):
            return Response(
                {"error": "verified_domain_required", "error_description": VERIFIED_DOMAIN_REQUIRED_ERROR},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            grant = _pending_grant(serializer.validated_data["user_code"], lock=True)
            if grant is None:
                return _invalid_code()
            application = OAuthApplication.objects.filter(client_id=grant.client_id).first()
            if application is None or not application.is_verified:
                return _unverified_client()
            requested = (grant.scope or "").split()
            kept = serializer.validated_data.get("scopes")
            if kept is not None:
                # A requested `x:write` also covers `x:read`, so the person can lower write access to read.
                if scopes_not_covered(requested, kept):
                    return _invalid_scope("You can only keep scopes the app asked for.")
                if scopes_not_covered(kept, _required_scopes(grant, application)):
                    return _invalid_scope("The app needs some of the scopes you removed. Keep those to approve.")
                grant.scope = " ".join(sorted(set(kept)))
            if block := _gateway_blocklist_block(
                request, grant.scope or "", access_level="team", scoped_team_ids=[team.id]
            ):
                return block
            grant.user = cast(User, request.user)
            grant.scoped_teams = [team.id]
            grant.status = OAuthDeviceGrant.AUTHORIZED
            grant.save(update_fields=["user", "scoped_teams", "status", "scope"])

        logger.info("oauth_device_grant_approved", client_id=grant.client_id[:64], team_id=team.id)
        _capture(
            request,
            "oauth_device_authorization_approved",
            grant,
            team_id=team.id,
            scopes_requested=len(requested),
            scopes_granted=len((grant.scope or "").split()),
            scopes_chosen=kept is not None and set(kept) != set(requested),
        )
        response = Response(DeviceDecisionSerializer({"status": grant.status}).data)
        clear_pending_oauth_connection_cookie(request._request, response)
        return response

    @extend_schema(request=DeviceUserCodeSerializer, responses={200: DeviceDecisionSerializer})
    @action(methods=["POST"], detail=False)
    def deny(self, request: Request) -> Response:
        """Refuse a device grant, so the client's next poll gets `access_denied`."""
        serializer = DeviceUserCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            grant = _pending_grant(serializer.validated_data["user_code"], lock=True)
            if grant is None:
                return _invalid_code()
            grant.user = cast(User, request.user)
            grant.status = OAuthDeviceGrant.DENIED
            grant.save(update_fields=["user", "status"])
        _capture(request, "oauth_device_authorization_denied", grant)
        response = Response(DeviceDecisionSerializer({"status": grant.status}).data)
        clear_pending_oauth_connection_cookie(request._request, response)
        return response
