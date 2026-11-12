"""Automated setup of enterprise-managed auth (EMA) through the `ema_issuer:manage` scope.

Without it, an admin who turns on EMA for an MCP client copies the client's ID-JAG issuer URL
into PostHog's XAA settings by hand. With it, the admin approves one consent screen, and the
client registers its issuer for that organization with a single call. From then on PostHog
accepts ID-JAGs from that issuer for every member whose email is on a verified domain of the
organization, without each member connecting through OAuth. Granting the scope is therefore
close to handing the client a sign-in for the whole organization, and every check here is
about who may grant it and to which client.

The flow:

1. The client sends the admin to `/oauth/authorize/` with `scope=ema_issuer:manage`, PKCE, and
   its usual `client_id`, `redirect_uri` and `resource`. The consent screen asks for exactly one
   organization the person administers and says what approving turns on.
2. The client exchanges the code at `/oauth/token/`. The response is a normal token response
   with `scope: "ema_issuer:manage"`, a five-minute `expires_in`, no refresh token, and one
   extra field, `ema_setup_endpoint`: the URL of `EmaTrustedIssuerView`.
3. The client calls `PUT <ema_setup_endpoint>` with the access token and
   `{"ema_issuer": "<issuer URL>"}`. PostHog stores the issuer as an XAA configuration for the
   token's organization and answers `{"aud_tenant": "<organization ID>"}`. The client puts that
   value in the `aud_tenant` claim of the ID-JAGs it issues later, and `id_jag` refuses an
   ID-JAG for this issuer whose `aud_tenant` is missing or names another organization. The call
   revokes the token, so it works once.

The setup call repeats every consent check, because membership, plan and domains can change
in between. A failure is an RFC 6749 style `error` and `error_description`, which the client
shows to the admin: `access_denied` when the person no longer administers the organization or
it can't use XAA, `issuer_in_use` when another configuration in the organization already trusts
the issuer, and
`invalid_request` for a malformed issuer. A second registration from the same client replaces
its configuration, so ID-JAGs from the previous issuer stop working.

The configuration is read-only in PostHog. Admins see it in the authentication settings and
turn it off by deleting it. The scope stays out of `scopes_supported` and the scope pickers:
only applications that PostHog staff marked with `can_manage_ema_issuer` can request it, and
those know about it without discovery. Removing that mark stops new setups and makes the ID-JAG
exchange reject every issuer the application registered, without deleting the configurations.
"""

import html
from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import urlsplit

from django.db import connection, transaction

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.helpers.email_utils import email_domain
from posthog.ip_restrictions import enforce_credential_ip_restrictions
from posthog.models.identity_provider_config import ConfigScope, DomainScope, IdentityProviderConfig, lock_id_jag_issuer
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthApplicationAccessLevel
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)

EMA_ISSUER_MANAGE_SCOPE = "ema_issuer:manage"

# The token only has to last from the token response to the setup call that follows it.
EMA_SETUP_TOKEN_EXPIRES_SECONDS = 300

EMA_SETUP_PATH = "/oauth/ema/trusted-issuer/"

_ISSUER_MAX_LENGTH = 512


def requests_ema_issuer(scopes: Iterable[str] | str | None) -> bool:
    if not scopes:
        return False
    tokens = scopes.split() if isinstance(scopes, str) else scopes
    return EMA_ISSUER_MANAGE_SCOPE in tokens


def client_may_manage_ema_issuer(application: OAuthApplication | None) -> bool:
    return bool(application is not None and application.can_manage_ema_issuer)


def ema_setup_endpoint() -> str:
    return absolute_uri(EMA_SETUP_PATH)


def _verified_domains_by_organization(organization_ids: Iterable[Any]) -> dict[str, list[str]]:
    rows = (
        OrganizationDomain.objects.verified_domains()
        .filter(organization_id__in=list(organization_ids))
        .order_by("domain")
        .values_list("organization_id", "domain")
    )
    domains: dict[str, list[str]] = {}
    for organization_id, domain in rows:
        domains.setdefault(str(organization_id), []).append(domain)
    return domains


def _ineligibility_reason(
    user: User, organization: Organization, membership_level: int | None, verified_domains: list[str]
) -> str | None:
    """Why this organization can't register an issuer, or None when it can.

    The consent screen shows the reason next to the organization, and the setup endpoint returns
    it to the client, which shows it to the admin.
    """
    if membership_level is None or membership_level < OrganizationMembership.Level.ADMIN:
        return "Only admins of this organization can set up enterprise-managed auth."
    if organization.enforce_verified_domains and (email_domain(user.email) or "").lower() not in {
        domain.lower() for domain in verified_domains
    }:
        return (
            "This organization only admits emails on its verified domains. Sign in with one of those, then try again."
        )
    if not organization.is_feature_available(AvailableFeature.XAA_AUTHENTICATION):
        return "This organization's plan doesn't include XAA. Upgrade the plan, then try again."
    if not verified_domains:
        return "This organization has no verified domain. Verify your email domain in PostHog's authentication settings, then try again."
    return None


def ema_consent_context(user: User) -> dict[str, object]:
    """What the consent screen needs to name the organization and what approving turns on."""
    memberships = list(OrganizationMembership.objects.filter(user=user).select_related("organization"))
    domains = _verified_domains_by_organization(membership.organization_id for membership in memberships)
    organizations = []
    for membership in memberships:
        organization = membership.organization
        verified_domains = domains.get(str(organization.id), [])
        organizations.append(
            {
                "id": str(organization.id),
                "name": organization.name,
                "verified_domains": verified_domains,
                "disabled_reason": _ineligibility_reason(user, organization, membership.level, verified_domains),
            }
        )
    organizations.sort(key=lambda org: (org["disabled_reason"] is not None, str(org["name"]).lower()))
    return {"scope": EMA_ISSUER_MANAGE_SCOPE, "organizations": organizations}


class EmaSetupError(Exception):
    """An RFC 6749 style error for the setup endpoint. The client shows `description` to the admin."""

    def __init__(self, error: str, description: str, http_status: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.http_status = http_status


def impersonation_refused() -> EmaSetupError:
    return EmaSetupError(
        "access_denied", "Enterprise-managed auth can't be set up while impersonating.", status.HTTP_403_FORBIDDEN
    )


def validate_ema_grant(
    user: User,
    application: OAuthApplication,
    scoped_organization_ids: list[str],
    *,
    impersonated: bool,
    access_level: str = OAuthApplicationAccessLevel.ORGANIZATION.value,
) -> Organization:
    """Checks a grant of `ema_issuer:manage` and returns the one organization it is for.

    Consent runs it before the authorization code is minted, and the setup endpoint runs it again,
    because membership, plan, and domains can all change in the minutes between the two.
    """
    if impersonated:
        raise impersonation_refused()
    if not client_may_manage_ema_issuer(application):
        raise EmaSetupError("invalid_scope", f"{EMA_ISSUER_MANAGE_SCOPE} is not available to this application.")
    if access_level != OAuthApplicationAccessLevel.ORGANIZATION.value or len(scoped_organization_ids) != 1:
        raise EmaSetupError("invalid_request", "Choose exactly one organization to set up enterprise-managed auth.")
    membership = (
        OrganizationMembership.objects.filter(user=user, organization_id=scoped_organization_ids[0])
        .select_related("organization")
        .first()
    )
    if membership is None:
        raise EmaSetupError("access_denied", "You aren't a member of this organization.", status.HTTP_403_FORBIDDEN)
    organization = membership.organization
    verified_domains = _verified_domains_by_organization([organization.id]).get(str(organization.id), [])
    reason = _ineligibility_reason(user, organization, membership.level, verified_domains)
    if reason:
        raise EmaSetupError("access_denied", reason, status.HTTP_403_FORBIDDEN)
    return organization


def _normalize_issuer(value: str) -> str:
    issuer = value.rstrip("/")
    try:
        parts = urlsplit(issuer)
        # `urlsplit` checks the port only when it is read.
        parts.port  # noqa: B018
    except ValueError:
        raise EmaSetupError("invalid_request", "ema_issuer is not a valid URL.")
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.query
        or parts.fragment
        or parts.username is not None
        or parts.password is not None
    ):
        raise EmaSetupError(
            "invalid_request", "ema_issuer must be an https URL without credentials, a query, or a fragment."
        )
    # Not resolved here: `id_jag._get_jwks_client` applies the SSRF guard each time it fetches from the issuer.
    return issuer


@frozen
class EmaRegistration:
    config: IdentityProviderConfig
    replaced_issuer: bool


def register_ema_issuer(access_token: OAuthAccessToken, raw_issuer: str) -> EmaRegistration:
    user = access_token.user
    application = access_token.application
    if user is None or application is None:
        raise EmaSetupError("invalid_token", "The access token is not valid.", status.HTTP_401_UNAUTHORIZED)
    if not requests_ema_issuer(access_token.scope):
        raise EmaSetupError(
            "insufficient_scope",
            f"The access token does not carry {EMA_ISSUER_MANAGE_SCOPE}.",
            status.HTTP_403_FORBIDDEN,
        )
    organization = validate_ema_grant(
        user,
        application,
        [str(org_id) for org_id in access_token.scoped_organizations or []],
        impersonated=access_token.impersonated_by_id is not None,
    )
    issuer = _normalize_issuer(raw_issuer)

    with transaction.atomic():
        # The token row lock makes a concurrent second call with the same token wait, then find the
        # token gone. The two advisory locks stop two calls from adding a second configuration for this
        # client, and two organizations from claiming one issuer. Every call takes them in this order.
        if not OAuthAccessToken.objects.select_for_update().filter(pk=access_token.pk).exists():
            raise EmaSetupError("invalid_token", "The access token was already used.", status.HTTP_401_UNAUTHORIZED)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"ema-registration:{organization.id}:{application.pk}"],
            )

        lock_id_jag_issuer(issuer)

        own_config = (
            IdentityProviderConfig.objects.select_for_update()
            .filter(organization=organization, id_jag_registered_by_application=application)
            .first()
        )
        # Other organizations may trust the same issuer. The email's verified domain and the required
        # `aud_tenant` already decide which organization an ID-JAG is for, and a global reservation
        # would let any organization block another's setup.
        others_with_issuer = (
            IdentityProviderConfig.objects.for_scope(ConfigScope.ID_JAG)
            .with_id_jag_issuer(issuer)
            .filter(organization=organization)
        )
        if own_config is not None:
            others_with_issuer = others_with_issuer.exclude(pk=own_config.pk)
        if others_with_issuer.exists():
            raise EmaSetupError(
                "issuer_in_use",
                "This organization already trusts this issuer in another XAA configuration. Remove that configuration in PostHog's authentication settings, then try again.",
                status.HTTP_409_CONFLICT,
            )

        replaced_issuer = own_config is not None and (own_config.id_jag_issuer_url or "").rstrip("/") != issuer
        config = own_config or IdentityProviderConfig(
            organization=organization, id_jag_registered_by_application=application
        )
        # The app name is HTML-escaped at ingestion.
        config.name = html.unescape(application.name or "")[:255]
        config.config_scope = ConfigScope.ID_JAG
        config.domain_scope = DomainScope.ALL
        config.id_jag_issuer_url = issuer
        config.id_jag_jwks_url = None
        # Not limited to the registering client: a vendor can set up with one of its clients and
        # exchange ID-JAGs with another. The issuer only signs for the vendor's own clients, and the
        # exchange already requires the presenting client to be the assertion's `client_id`.
        config.id_jag_allowed_clients = []
        config.save()
        access_token.revoke()

    return EmaRegistration(config=config, replaced_issuer=replaced_issuer)


class EmaTrustedIssuerSerializer(serializers.Serializer):
    ema_issuer = serializers.CharField(
        max_length=_ISSUER_MAX_LENGTH,
        help_text="Issuer URL of the ID-JAGs the client will present for this organization.",
    )


class EmaTrustedIssuerView(APIView):
    """The `ema_setup_endpoint` named in the token response of an `ema_issuer:manage` grant.

    The access token is single use: a successful call revokes it.
    """

    authentication_classes = [OAuthAccessTokenAuthentication]
    permission_classes: list = []

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, exceptions.NotAuthenticated | exceptions.AuthenticationFailed):
            response = Response(
                {"error": "invalid_token", "error_description": "The access token is missing, expired, or revoked."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            response["WWW-Authenticate"] = 'Bearer error="invalid_token"'
            return response
        if isinstance(exc, exceptions.ParseError):
            return Response(
                {"error": "invalid_request", "error_description": "The request body must be a JSON object."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().handle_exception(exc)

    @extend_schema(exclude=True)
    def put(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        authenticator = request.successful_authenticator
        if not isinstance(authenticator, OAuthAccessTokenAuthentication):
            raise exceptions.NotAuthenticated()
        access_token = authenticator.access_token

        serializer = EmaTrustedIssuerSerializer(data=request.data)
        try:
            try:
                enforce_credential_ip_restrictions(
                    request, [str(org_id) for org_id in access_token.scoped_organizations or []], []
                )
            except exceptions.PermissionDenied as error:
                raise EmaSetupError("access_denied", str(error.detail), status.HTTP_403_FORBIDDEN)
            if not serializer.is_valid():
                raise EmaSetupError(
                    "invalid_request",
                    f"The request body must be a JSON object with ema_issuer, at most {_ISSUER_MAX_LENGTH} characters.",
                )
            registration = register_ema_issuer(access_token, serializer.validated_data["ema_issuer"])
        except EmaSetupError as error:
            logger.info(
                "ema_issuer_registration_rejected",
                error=error.error,
                application_id=str(access_token.application_id),
                user_id=access_token.user_id,
            )
            return Response(
                {"error": error.error, "error_description": error.description},
                status=error.http_status,
            )

        config = registration.config
        organization = config.organization
        posthoganalytics.capture(
            distinct_id=str(cast(User, access_token.user).distinct_id),
            event="ema issuer registered",
            properties={
                "client_name": cast(OAuthApplication, access_token.application).name,
                "application_id": str(access_token.application_id),
                "identity_provider_config_id": str(config.id),
                "replaced_issuer": registration.replaced_issuer,
            },
            groups=groups(organization),
        )
        logger.info(
            "ema_issuer_registered",
            organization_id=str(organization.id),
            identity_provider_config_id=str(config.id),
            application_id=str(access_token.application_id),
            replaced_issuer=registration.replaced_issuer,
        )
        return Response({"aud_tenant": str(organization.id)}, status=status.HTTP_200_OK)
