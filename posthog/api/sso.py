import json
import base64
from typing import Any, cast
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http.response import HttpResponse
from django.urls.base import reverse

import structlog
import posthoganalytics
import redis.exceptions as redis_exceptions
from onelogin.saml2.xml_utils import OneLogin_Saml2_XML
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from social_core.backends.google import GoogleOAuth2
from social_core.backends.saml import (
    OID_COMMON_NAME,
    OID_GIVEN_NAME,
    OID_MAIL,
    OID_SURNAME,
    OID_USERID,
    SAMLAuth,
    SAMLIdentityProvider,
)
from social_core.exceptions import AuthFailed, AuthMissingParameter
from social_django.models import UserSocialAuth
from social_django.strategy import DjangoStrategy
from social_django.utils import load_backend, load_strategy

from posthog.api.scim.utils import mask_email
from posthog.constants import AvailableFeature
from posthog.helpers.email_utils import EmailLookupHandler
from posthog.helpers.sso import UNVERIFIED_SOCIAL_EMAIL_ERROR
from posthog.models.identity_provider_config import IdentityProviderConfig, has_verified_organization_domain_q
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.redis import get_client

saml_logger = structlog.get_logger("posthog.auth.saml")


def _saml_log_context(email: str, organization_id: UUID | None = None) -> dict[str, Any]:

    ctx: dict[str, Any] = {
        "masked_email": mask_email(email),
        "email_domain": email.split("@")[-1].lower(),
    }

    try:
        user = EmailLookupHandler.get_user_by_email(email, is_active=None)
        if user:
            ctx["user_id"] = str(user.id)
            if organization_id:
                membership = user.organization_memberships.filter(organization_id=organization_id).first()
                ctx["membership_level"] = membership.get_level_display() if membership else "none"
        else:
            ctx["user_id"] = "unknown"
    except Exception:
        pass

    return ctx


@api_view(["GET"])
def saml_metadata_view(request, *args, **kwargs):
    if (
        not request.user.organization_memberships.get(organization=request.user.organization).level
        >= OrganizationMembership.Level.ADMIN
    ):
        raise PermissionDenied("You need to be an administrator or owner to access this resource.")

    complete_url = reverse("social:complete", args=("saml",))
    saml_backend = load_backend(load_strategy(request), "saml", redirect_uri=complete_url)
    metadata, errors = saml_backend.generate_metadata_xml()

    if not errors:
        return HttpResponse(content=metadata, content_type="text/xml")


# OASIS SAML bindings cap RelayState at 80 bytes; the cache TTL only needs to outlast the IdP round trip.
SAML_RELAY_STATE_CACHE_TTL_SECONDS = 60 * 10


def _saml_relay_state_cache_key(key: str) -> str:
    return f"saml_relay_state:{key}"


def _relay_state_from_json(raw: str | bytes) -> dict[str, Any] | None:
    try:
        state = json.loads(raw)
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


def _store_saml_relay_state(state: dict[str, Any]) -> str:
    key = str(uuid4())
    try:
        get_client().setex(_saml_relay_state_cache_key(key), SAML_RELAY_STATE_CACHE_TTL_SECONDS, json.dumps(state))
    except redis_exceptions.RedisError:
        # Sessions are DB-backed, so a Redis outage must not block login. Send the pre-cache JSON
        # instead: the IdP may refuse it above the RelayState cap, but failing the flow is worse.
        return json.dumps(state)
    return key


def _load_saml_relay_state(key: str) -> dict[str, Any] | None:
    try:
        raw = get_client().get(_saml_relay_state_cache_key(key))
    except redis_exceptions.RedisError:
        return None
    return _relay_state_from_json(raw) if raw else None


class MultitenantSAMLAuth(SAMLAuth):
    """
    Implements our own version of SAML auth that supports multitenancy. Instead of relying on instance-based config via env vars,
    each organization can have multiple verified domains each with its own SAML configuration.
    """

    def auth_complete(self, *args, **kwargs):
        # attempt to recover from missing relay state in idp-initiated SAML
        self._recover_idp_initiated_relay_state()

        try:
            result = super().auth_complete(*args, **kwargs)
            saml_logger.info("saml_auth_complete")
            return result
        except Exception as e:
            posthoganalytics.tag("request_data", json.dumps(self.strategy.request_data()))
            saml_logger.warning("saml_auth_complete_failed", error=str(e))
            raise

    def _recover_idp_initiated_relay_state(self) -> None:
        """
        SP-initiated logins carry a RelayState holding the linked IdP config's identifier, which
        is how we route an assertion to the right tenant. IdP-initiated logins don't: the IdP
        either omits RelayState (Azure AD) or sends its own value (e.g. an app URL). When the
        RelayState doesn't map to a config, recover the tenant from the Response's <Issuer> (the
        IdP entity ID, stored on the `IdentityProviderConfig` as `saml_entity_id`) and inject a
        RelayState so the rest of the flow proceeds unchanged.
        """
        data = self.strategy.request_data()
        saml_response = data.get("SAMLResponse")
        if not saml_response:
            return

        if self._relay_state_points_to_config(data.get("RelayState")):
            return  # SP-initiated: RelayState already identifies the tenant

        issuer = self._extract_response_issuer(saml_response)
        if not issuer:
            return

        # `saml_entity_id` has no uniqueness constraint, so only act on an unambiguous config —
        # never guess which tenant an unsolicited assertion belongs to. The config can be linked
        # to multiple domains, so resolve it before choosing a RelayState.
        configs = list(
            # nosemgrep: idor-lookup-without-org (pre-auth SAML routing by IdP entity id; the assertion signature is verified afterwards)
            IdentityProviderConfig.objects.filter(
                has_verified_organization_domain_q(),
                saml_entity_id=issuer,
            ).distinct()
        )
        if len(configs) != 1:
            if len(configs) > 1:
                saml_logger.warning("saml_idp_initiated_ambiguous_issuer", issuer=issuer, count=len(configs))
            return

        idp_config = configs[0]
        relay_state = idp_config.saml_relay_state
        if not idp_config.has_saml or not relay_state:
            return

        saml_logger.info(
            "saml_idp_initiated_relay_state_recovered",
            identity_provider_config_id=str(idp_config.id),
            organization_id=str(idp_config.organization_id),
        )
        # Inject the config identifier so the standard flow can route the response to the tenant.
        strategy = cast(DjangoStrategy, self.strategy)
        mutable_post = strategy.request.POST.copy()
        mutable_post["RelayState"] = relay_state
        # django-stubs types request.POST as immutable; reassigning it is valid at runtime.
        strategy.request.POST = mutable_post  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

    def parse_relay_state(self, relay_state_str: str) -> dict:
        # A miss still routes the pre-cache JSON payload, an IdP-supplied value, or an expired key
        # through the base parser, which sends the last two to the IdP-initiated recovery.
        stored = _load_saml_relay_state(relay_state_str)
        return stored if stored is not None else super().parse_relay_state(relay_state_str)

    def _relay_state_points_to_config(self, relay_state_str: str | None) -> bool:
        if not relay_state_str:
            return False
        candidate = self.parse_relay_state(relay_state_str).get("idp")
        if not candidate:
            return False
        try:
            # nosemgrep: idor-lookup-without-org (pre-auth SAML routing check by IdP config identifier)
            return (
                IdentityProviderConfig.objects.filter(
                    has_verified_organization_domain_q(),
                    saml_relay_state=candidate,
                )
                .distinct()
                .exists()
            )
        except (DjangoValidationError, ValueError):
            return False  # malformed or IdP-supplied value

    @staticmethod
    def _extract_response_issuer(saml_response_b64: str) -> str | None:
        # POST-binding SAMLResponse is base64-encoded (not deflated). Parsing is XXE-safe
        # (onelogin forbids DTDs/entities); the signature is still verified afterwards.
        try:
            document = OneLogin_Saml2_XML.to_etree(base64.b64decode(saml_response_b64))
            issuer_nodes = OneLogin_Saml2_XML.query(document, "/samlp:Response/saml:Issuer")
        except Exception:
            return None
        if not issuer_nodes:
            return None
        return (OneLogin_Saml2_XML.element_text(issuer_nodes[0]) or "").strip() or None

    def get_idp(self, identity_provider_config_or_id: IdentityProviderConfig | str | None) -> SAMLIdentityProvider:
        if identity_provider_config_or_id is None:
            saml_logger.warning("saml_idp_lookup_failed", idp_id="None")
            raise AuthFailed(self, "Authentication request is invalid. Invalid RelayState.")

        if isinstance(identity_provider_config_or_id, IdentityProviderConfig):
            idp_config = identity_provider_config_or_id
        else:
            try:
                # nosemgrep: idor-lookup-without-org (pre-auth SAML flow, lookup by config identifier on verified configs)
                idp_config = (
                    IdentityProviderConfig.objects.filter(
                        has_verified_organization_domain_q(),
                        saml_relay_state=identity_provider_config_or_id,
                    )
                    .distinct()
                    .get()
                )
            except (
                IdentityProviderConfig.DoesNotExist,
                IdentityProviderConfig.MultipleObjectsReturned,
                DjangoValidationError,
            ):
                saml_logger.warning("saml_idp_lookup_failed", idp_id=str(identity_provider_config_or_id))
                raise AuthFailed(self, "Authentication request is invalid. Invalid RelayState.")

        if not idp_config.organization.is_feature_available(AvailableFeature.SAML):
            saml_logger.warning(
                "saml_license_missing",
                organization_id=str(idp_config.organization_id),
            )
            raise AuthFailed(
                self,
                "Your organization does not have the required license to use SAML.",
            )

        if not idp_config.saml_relay_state:
            raise AuthFailed(self, "Authentication request is invalid. Invalid RelayState.")

        return SAMLIdentityProvider(
            self,
            idp_config.saml_relay_state,
            entity_id=idp_config.saml_entity_id,
            url=idp_config.saml_acs_url,
            x509cert=idp_config.saml_x509_cert,
        )

    def auth_url(self):
        email = self.strategy.request_data().get("email")

        if not email:
            raise AuthMissingParameter(self, "email")

        idp_configs = list(IdentityProviderConfig.objects.saml_for_email(email)[:2])
        if len(idp_configs) == 0:
            saml_logger.warning("saml_not_configured", **_saml_log_context(email))
            raise AuthFailed(self, "SAML not configured for this user.")
        if len(idp_configs) > 1:
            saml_logger.warning("saml_multiple_configs", **_saml_log_context(email))
            raise AuthFailed(self, "Multiple SAML configurations found for this user.")

        idp_config = idp_configs[0]
        saml_logger.info(
            "saml_auth_redirect",
            organization_id=str(idp_config.organization_id),
            **_saml_log_context(email, idp_config.organization_id),
        )
        identity_provider = self.get_idp(idp_config)
        auth = self._create_saml_auth(idp=identity_provider)
        # `return_to` sets the RelayState, a value the IdP echoes back in its POST to the
        # (shared) auth_complete URL. The session cookie is SameSite=Lax and so is dropped on
        # the IdP's cross-site POST, which would otherwise lose `next` and send the user to `/`;
        # carrying it in RelayState lets the base `auth_complete` recover it for the post-login
        # redirect. `idp` carries the linked config identifier since multiple IdPs share the URL.
        # We deliberately omit the session key that upstream `SAMLAuth.auth_url` also packs into
        # RelayState: it would be disclosed to the (potentially attacker-controlled) IdP in the
        # redirect, and `next` alone is enough to recover the redirect without it.
        relay_state = {"idp": identity_provider.name, "next": self.data.get("next")}
        return auth.login(return_to=_store_saml_relay_state(relay_state))

    def _get_attr(
        self,
        response_attributes: dict[str, Any],
        attribute_names: list[str],
        optional: bool = False,
    ) -> str:
        """
        Fetches a specific attribute from the SAML response, attempting with multiple different attribute names.
        We attempt multiple attribute names to make it easier for admins to configure SAML (less configuration to set).
        """
        output: str | list[str] | None = None
        for _attr in attribute_names:
            if _attr in response_attributes:
                output = response_attributes[_attr]
                break

        if not output and not optional:
            raise AuthMissingParameter(self, attribute_names[0])

        if isinstance(output, list):
            output = output[0]

        return output or ""

    def get_user_details(self, response) -> dict[str, str | None]:
        """
        Overridden to find attributes across multiple possible names.
        """
        attributes = response["attributes"]
        email = self._get_attr(
            attributes,
            [
                "email",
                "EMAIL",
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                OID_MAIL,
            ],
        )

        self._validate_email_domain(response, email)

        return {
            "fullname": self._get_attr(
                attributes,
                ["full_name", "FULL_NAME", "fullName", OID_COMMON_NAME],
                optional=True,
            ),
            "first_name": self._get_attr(
                attributes,
                [
                    "first_name",
                    "FIRST_NAME",
                    "firstName",
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
                    OID_GIVEN_NAME,
                ],
                optional=True,
            ),
            "last_name": self._get_attr(
                attributes,
                [
                    "last_name",
                    "LAST_NAME",
                    "lastName",
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname",
                    OID_SURNAME,
                ],
                optional=True,
            ),
            "email": email,
        }

    def _validate_email_domain(self, response: dict, email: str) -> None:
        """
        Ensures the email domain from the SAML assertion is consistent with
        the OrganizationDomain that owns this IdP configuration.
        """
        idp_name = response.get("idp_name")
        if not idp_name:
            saml_logger.warning(
                "saml_email_domain_validation_failed",
                reason="missing_idp_name",
                **_saml_log_context(email),
            )
            raise AuthFailed(self, "Authentication request is invalid. Missing IdP identifier.")

        try:
            # nosemgrep: idor-lookup-without-org (pre-auth SAML validation, config identifier from IdP round-trip)
            idp_config = IdentityProviderConfig.objects.get(saml_relay_state=idp_name)
        except (IdentityProviderConfig.DoesNotExist, DjangoValidationError):
            saml_logger.warning(
                "saml_email_domain_validation_failed",
                reason="invalid_idp",
                idp_id=str(idp_name),
                **_saml_log_context(email),
            )
            raise AuthFailed(self, "Authentication request is invalid. Invalid IdP identifier.")

        # A config can back several verified domains, and an assertion is valid for any of them.
        configured_domains = {
            domain.lower()
            for domain in idp_config.organization_domains.filter(verified_at__isnull=False).values_list(
                "domain", flat=True
            )
        }
        if email.rsplit("@", 1)[-1].lower() in configured_domains:
            return

        if not configured_domains:
            # SAML stays gated behind domain verification, so a config that backs none can't
            # authorize anyone, whatever its RelayState resolves to.
            saml_logger.warning(
                "saml_email_domain_validation_failed",
                reason="no_verified_domain",
                idp_id=str(idp_name),
                **_saml_log_context(email),
            )
            raise AuthFailed(self, "Authentication request is invalid. Invalid IdP identifier.")

        saml_logger.warning(
            "saml_email_domain_mismatch",
            configured_domains=sorted(configured_domains),
            organization_id=str(idp_config.organization_id),
            **_saml_log_context(email, idp_config.organization_id),
        )
        raise AuthFailed(
            self,
            "Authentication failed. The email domain from your identity provider does not match the configured domain.",
        )

    def get_user_id(self, details, response):
        """
        Overridden to find user ID across multiple attribute names.
        Get the permanent ID for this user from the response.
        """
        USER_ID_ATTRIBUTES = ["name_id", "NAME_ID", "nameId", OID_USERID]
        uid = self._get_attr(response["attributes"], USER_ID_ATTRIBUTES)
        return f"{response['idp_name']}:{uid}"


class CustomGoogleOAuth2(GoogleOAuth2):
    def auth_extra_arguments(self):
        extra_args = super().auth_extra_arguments()
        is_reauth = self.strategy.request_get().get("reauth") == "true"
        if not is_reauth:
            prompt_tokens = [token for token in str(extra_args.get("prompt", "")).split() if token]
            if "select_account" not in prompt_tokens:
                prompt_tokens.append("select_account")
            extra_args["prompt"] = " ".join(prompt_tokens)

        email = self.strategy.request_get().get("email")

        if email:
            extra_args["login_hint"] = email

        return extra_args

    def get_user_id(self, details, response):
        """
        Retrieve and migrate Google OAuth user identification.

        Note: While social-auth-core supports using Google's sub claim via
        settings.USE_UNIQUE_USER_ID = True, this setting was not enabled historically
        in our application. This led to emails being stored as uids instead of the
        more stable Google sub identifier.

        'sub' (subject identifier) is part of OpenID Connect and is guaranteed to be a
        stable, unique identifier for the user within Google's system. It's designed
        specifically for authentication purposes and won't change even if the user changes
        their email or other profile details.

        This method handles two types of user identification:
        1. Legacy users: Originally stored with email as their uid (due to missing USE_UNIQUE_USER_ID)
        2. New users: Using Google's sub claim (unique identifier) as uid

        The method first checks if a user exists with the sub as uid. If not found,
        it looks for a legacy user with email as uid and migrates them to use sub.
        This ensures a smooth transition from email-based to sub-based identification
        while maintaining backward compatibility.

        Args:
            details: User details dictionary from OAuth response
            response: Full OAuth response from Google

        Returns:
            str: The Google sub claim to be used as uid
        """
        email = response.get("email")
        sub = response.get("sub")

        if not sub:
            raise ValueError("Google OAuth response missing 'sub' claim")

        try:
            # First try: Find user by sub (preferred method)
            social_auth = UserSocialAuth.objects.get(provider="google-oauth2", uid=sub)
            return sub
        except UserSocialAuth.DoesNotExist:
            pass

        try:
            # Second try: Find and migrate legacy user using email as uid
            social_auth = UserSocialAuth.objects.get(provider="google-oauth2", uid=email)
            # This lookup resolves the account by email address, so the email has to be verified,
            # the same as for `associate_by_email`.
            if response.get("email_verified") is not True:
                raise AuthFailed(self, UNVERIFIED_SOCIAL_EMAIL_ERROR)
            # Migrate user from email to sub
            social_auth.uid = sub
            social_auth.save()
            return sub
        except UserSocialAuth.DoesNotExist:
            # No existing user found - use sub for new account
            return sub


def social_auth_allowed(backend, details, response, *args, **kwargs) -> None:
    email = details.get("email")
    # Check if SSO enforcement is enabled for this email address
    sso_enforcement = OrganizationDomain.objects.get_sso_enforcement_for_email_address(email)
    if sso_enforcement is None or sso_enforcement == backend.name:
        return

    saml_logger.warning(
        "sso_enforcement_blocked_login",
        attempted_backend=backend.name,
        enforced_backend=sso_enforcement,
        **(_saml_log_context(email) if email else {"masked_email": "unknown"}),
    )

    if sso_enforcement == "saml":
        raise AuthFailed(backend, "saml_sso_enforced")
    elif sso_enforcement == "google-oauth2":
        raise AuthFailed(backend, "google_sso_enforced")
    elif sso_enforcement == "github":
        raise AuthFailed(backend, "github_sso_enforced")
    elif sso_enforcement == "gitlab":
        raise AuthFailed(backend, "gitlab_sso_enforced")
    else:
        # catch-all in case we missed a case above
        raise AuthFailed(backend, "sso_enforced", email)
