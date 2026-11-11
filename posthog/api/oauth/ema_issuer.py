"""Automated setup of enterprise-managed auth (EMA) through the `ema_issuer:manage` scope.

An organization admin approves one consent screen, and the client then registers its ID-JAG
issuer for that organization with a single call to the setup endpoint. From then on PostHog
accepts ID-JAGs from that issuer for every member whose email is on a verified domain of the
organization, without each member connecting through OAuth. Granting the scope is therefore
close to handing the client a sign-in for the whole organization, and every check here is
about who may grant it and to which client.

The scope stays out of `scopes_supported` and the scope pickers: only clients listed in
`EMA_ISSUER_MANAGE_CLIENT_IDS` can request it, and those know about it without discovery.
"""

import html
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.db import connection, models, transaction

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
from posthog.models.identity_provider_config import ConfigScope, DomainScope, IdentityProviderConfig
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
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


def client_may_manage_ema_issuer(client_id: str | None) -> bool:
    return bool(client_id) and client_id in settings.EMA_ISSUER_MANAGE_CLIENT_IDS


def ema_setup_endpoint() -> str:
    return absolute_uri(EMA_SETUP_PATH)


def _verified_domains(organization_id: Any) -> list[str]:
    return sorted(
        OrganizationDomain.objects.filter(organization_id=organization_id, verified_at__isnull=False).values_list(
            "domain", flat=True
        )
    )


def _ineligibility_reason(
    organization: Organization, membership_level: int | None, verified_domains: list[str]
) -> str | None:
    """Why this organization can't register an issuer, or None when it can.

    The consent screen shows the reason next to the organization, and the setup endpoint returns
    it to the client, which shows it to the admin.
    """
    if membership_level is None or membership_level < OrganizationMembership.Level.ADMIN:
        return "Only admins of this organization can set up enterprise-managed auth."
    if not organization.is_feature_available(AvailableFeature.XAA_AUTHENTICATION):
        return "This organization's plan doesn't include XAA. Upgrade the plan, then try again."
    if not verified_domains:
        return "This organization has no verified domain. Verify your email domain in PostHog's authentication settings, then try again."
    return None


@frozen
class EmaConsentOrganization:
    id: str
    name: str
    verified_domains: list[str]
    disabled_reason: str | None


def ema_consent_context(user: User, application: OAuthApplication) -> dict[str, object]:
    """What the consent screen needs to name the organization and what approving turns on."""
    memberships = OrganizationMembership.objects.filter(user=user).select_related("organization")
    organizations: list[EmaConsentOrganization] = []
    for membership in memberships:
        organization = membership.organization
        verified_domains = _verified_domains(organization.id)
        organizations.append(
            EmaConsentOrganization(
                id=str(organization.id),
                name=organization.name,
                verified_domains=verified_domains,
                disabled_reason=_ineligibility_reason(organization, membership.level, verified_domains),
            )
        )
    organizations.sort(key=lambda org: (org.disabled_reason is not None, org.name.lower()))
    return {
        "scope": EMA_ISSUER_MANAGE_SCOPE,
        "organizations": [
            {
                "id": org.id,
                "name": org.name,
                "verified_domains": org.verified_domains,
                "disabled_reason": org.disabled_reason,
            }
            for org in organizations
        ],
    }


class EmaSetupError(Exception):
    """An RFC 6749 style error for the setup endpoint. The client shows `description` to the admin."""

    def __init__(self, error: str, description: str, http_status: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.http_status = http_status


def validate_ema_grant(user: User, application: OAuthApplication, scoped_organization_ids: list[str]) -> None:
    """Checks a consent grant of `ema_issuer:manage` before the authorization code is minted.

    The setup endpoint repeats every check, because membership, plan, and domains can all change
    in the minutes between consent and the setup call.
    """
    if not client_may_manage_ema_issuer(application.client_id):
        raise EmaSetupError("invalid_scope", f"{EMA_ISSUER_MANAGE_SCOPE} is not available to this application.")
    if len(scoped_organization_ids) != 1:
        raise EmaSetupError("invalid_request", "Choose exactly one organization to set up enterprise-managed auth.")
    membership = (
        OrganizationMembership.objects.filter(user=user, organization_id=scoped_organization_ids[0])
        .select_related("organization")
        .first()
    )
    if membership is None:
        raise EmaSetupError("access_denied", "You aren't a member of this organization.", status.HTTP_403_FORBIDDEN)
    organization = membership.organization
    reason = _ineligibility_reason(organization, membership.level, _verified_domains(organization.id))
    if reason:
        raise EmaSetupError("access_denied", reason, status.HTTP_403_FORBIDDEN)


def _normalize_issuer(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EmaSetupError("invalid_request", "ema_issuer must be a non-empty string.")
    issuer = value.strip().rstrip("/")
    if len(issuer) > _ISSUER_MAX_LENGTH:
        raise EmaSetupError("invalid_request", f"ema_issuer must be at most {_ISSUER_MAX_LENGTH} characters.")
    parts = urlsplit(issuer)
    if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment or parts.username:
        raise EmaSetupError("invalid_request", "ema_issuer must be an https URL without a query or fragment.")
    # Not resolved here: `id_jag._get_jwks_client` applies the SSRF guard each time it fetches from the issuer.
    return issuer


def _configs_with_issuer(issuer: str) -> models.QuerySet[IdentityProviderConfig]:
    return (
        IdentityProviderConfig.objects.annotate(
            normalized_id_jag_issuer_url=models.Func(
                "id_jag_issuer_url",
                models.Value("/"),
                function="RTRIM",
                output_field=models.CharField(),
            )
        )
        .filter(normalized_id_jag_issuer_url=issuer)
        .select_related("organization")
    )


@frozen
class EmaRegistration:
    config: IdentityProviderConfig
    organization: Organization
    replaced_issuer: str | None


def register_ema_issuer(access_token: OAuthAccessToken, raw_issuer: object) -> EmaRegistration:
    user = access_token.user
    application = access_token.application
    if user is None or application is None:
        raise EmaSetupError("invalid_token", "The access token is not valid.", status.HTTP_401_UNAUTHORIZED)
    if EMA_ISSUER_MANAGE_SCOPE not in (access_token.scope or "").split():
        raise EmaSetupError(
            "insufficient_scope",
            f"The access token does not carry {EMA_ISSUER_MANAGE_SCOPE}.",
            status.HTTP_403_FORBIDDEN,
        )
    if access_token.impersonated_by_id is not None:
        raise EmaSetupError(
            "access_denied", "Enterprise-managed auth can't be set up while impersonating.", status.HTTP_403_FORBIDDEN
        )
    validate_ema_grant(user, application, [str(org_id) for org_id in access_token.scoped_organizations or []])

    issuer = _normalize_issuer(raw_issuer)
    organization_id = (access_token.scoped_organizations or [])[0]

    with transaction.atomic():
        # Two organizations registering the same issuer at once would both pass the in-use check.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"ema-issuer:{issuer}"])

        own_config = (
            IdentityProviderConfig.objects.select_for_update()
            .filter(organization_id=organization_id, id_jag_registered_by_application=application)
            .first()
        )
        for other in _configs_with_issuer(issuer):
            if own_config is not None and other.pk == own_config.pk:
                continue
            if str(other.organization_id) == str(organization_id):
                raise EmaSetupError(
                    "issuer_in_use",
                    "This organization already trusts this issuer in another XAA configuration. Remove that configuration in PostHog's authentication settings, then try again.",
                    status.HTTP_409_CONFLICT,
                )
            raise EmaSetupError(
                "issuer_in_use",
                "Another PostHog organization already trusts this issuer. Remove it from that organization's authentication settings, then try again.",
                status.HTTP_409_CONFLICT,
            )

        replaced_issuer = own_config.id_jag_issuer_url if own_config is not None else None
        config = own_config or IdentityProviderConfig(
            organization_id=organization_id, id_jag_registered_by_application=application
        )
        # The app name is HTML-escaped at ingestion.
        config.name = html.unescape(application.name or "")[:255]
        config.config_scope = ConfigScope.ID_JAG
        config.domain_scope = DomainScope.ALL
        config.id_jag_issuer_url = issuer
        config.id_jag_jwks_url = None
        # The ID-JAGs this issuer signs are for the client that registered it, so no other client
        # can exchange them.
        config.id_jag_allowed_clients = [application.client_id]
        config.save()

    return EmaRegistration(
        config=config,
        organization=config.organization,
        replaced_issuer=replaced_issuer if replaced_issuer and replaced_issuer.rstrip("/") != issuer else None,
    )


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
            if not serializer.is_valid():
                raise EmaSetupError("invalid_request", "The request body must be a JSON object with ema_issuer.")
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

        access_token.revoke()

        organization = registration.organization
        posthoganalytics.capture(
            distinct_id=str(access_token.user.distinct_id) if access_token.user else "unknown",
            event="ema issuer registered",
            properties={
                "client_name": access_token.application.name if access_token.application else None,
                "application_id": str(access_token.application_id),
                "identity_provider_config_id": str(registration.config.id),
                "replaced_issuer": registration.replaced_issuer is not None,
            },
            groups=groups(organization),
        )
        logger.info(
            "ema_issuer_registered",
            organization_id=str(organization.id),
            identity_provider_config_id=str(registration.config.id),
            application_id=str(access_token.application_id),
            replaced_issuer=registration.replaced_issuer is not None,
        )
        return Response({"aud_tenant": str(organization.id)}, status=status.HTTP_200_OK)
