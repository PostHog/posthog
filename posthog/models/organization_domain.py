import secrets
from typing import TYPE_CHECKING, Optional

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

import structlog
import dns.resolver

from posthog.constants import AvailableFeature
from posthog.dns_utils import dnssec_resolver
from posthog.models import Organization
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.identity_provider_config import ConfigScope, DomainScope, IdentityProviderConfig, saml_configured_q
from posthog.models.linked_identity_provider_config import LinkedIdentityProviderConfig
from posthog.models.utils import UUIDTModel
from posthog.utils import get_instance_available_sso_providers

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)


def generate_verification_challenge() -> str:
    return secrets.token_urlsafe(32)


class OrganizationDomainManager(models.Manager):
    def verified_domains(self):
        # TODO: Verification becomes stale on Cloud if not reverified after a certain period.
        # INVARIANT for that future work: never clear `verified_at` while the owning organization
        # has `enforce_verified_domains` on — the domain would drop out of the enforcement
        # allow-list and lock out every member on it at once, admins included. Suspend or flag
        # instead of clearing.
        return self.exclude(verified_at__isnull=True)

    def get_verified_for_email_address(self, email: str) -> Optional["OrganizationDomain"]:
        """
        Returns an `OrganizationDomain` configuration for a specific email address (if it exists and is verified),
        using the domain of the email address
        """
        domain = email[email.index("@") + 1 :]
        return self.verified_domains().filter(domain__iexact=domain).first()

    def get_sso_enforcement_for_email_address(
        self, email: str, organization: Organization | None = None
    ) -> Optional[str]:
        """
        Returns the specific `sso_enforcement` applicable for an email address or an `OrganizationDomain` objects.
        Validates SSO providers are properly configured and all the proper licenses exist.
        """
        domain = email[email.index("@") + 1 :]
        queryset = self.verified_domains().filter(domain__iexact=domain).exclude(sso_enforcement="")

        if organization is not None:
            queryset = queryset.filter(organization=organization)

        query = queryset.values(
            "sso_enforcement", "organization_id", "organization__available_product_features"
        ).first()

        if not query:
            return None

        candidate_sso_enforcement = query["sso_enforcement"]

        available_product_features = query["organization__available_product_features"]
        available_product_feature_keys = [feature["key"] for feature in available_product_features]
        # Check organization has a license to enforce SSO
        if AvailableFeature.SSO_ENFORCEMENT not in available_product_feature_keys:
            logger.warning(
                f"🤑🚪 SSO is enforced for domain {domain} but the organization does not have the proper license.",
                domain=domain,
                organization=str(query["organization_id"]),
            )
            return None

        # Check SSO provider is properly configured and has a valid license (to use the specific SSO) if applicable
        if candidate_sso_enforcement == "saml":
            # SAML uses special handling because it's configured at the domain level instead of at the instance-level
            if AvailableFeature.SAML not in available_product_feature_keys:
                logger.warning(
                    f"🤑🚪 SAML SSO is enforced for domain {domain} but the organization does not have a SAML license.",
                    domain=domain,
                    organization=str(query["organization_id"]),
                )
                return None
        else:
            sso_providers = get_instance_available_sso_providers()
            if not sso_providers[candidate_sso_enforcement]:
                logger.warning(
                    f"SSO is enforced for domain {domain} but the SSO provider ({candidate_sso_enforcement}) is not properly configured.",
                    domain=domain,
                    candidate_sso_enforcement=candidate_sso_enforcement,
                )
                return None

        return candidate_sso_enforcement

    def is_domain_verified_for_organization(self, email: str, organization: Organization) -> bool:
        """Whether the domain of `email` is a verified domain owned by `organization`."""
        if "@" not in email:
            return False
        domain = email[email.index("@") + 1 :]
        return self.verified_domains().filter(organization=organization, domain__iexact=domain).exists()

    def is_email_blocked_by_domain_enforcement(self, email: str, organization: Organization) -> bool:
        """
        Whether a login or join for `email` into `organization` should be blocked: the org requires
        a verified email domain, and `email`'s domain is not one of the org's verified domains.
        """
        if not organization.enforce_verified_domains:
            return False
        return not self.is_domain_verified_for_organization(email, organization)

    def is_access_blocked_by_domain_enforcement(self, user: "User") -> bool:
        """
        Whether `user` should be denied access to the organization they're currently in.

        Scoped to the current organization, matching `enforce_2fa`: one organization's setting must
        not lock a member out of the other organizations they belong to.
        """
        organization = user.organization
        if organization is None:
            return False
        return self.is_email_blocked_by_domain_enforcement(user.email, organization)


class OrganizationDomain(ModelActivityMixin, UUIDTModel):
    objects: OrganizationDomainManager = OrganizationDomainManager()

    activity_logging_on_delete = True

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="domains")
    domain = models.CharField(max_length=128, unique=True)
    verification_challenge = models.CharField(max_length=128, default=generate_verification_challenge)
    verified_at = models.DateTimeField(
        null=True, blank=True, default=None
    )  # verification (through DNS) is only used for PostHog Cloud; on self-hosted we take all domains as verified
    last_verification_retry = models.DateTimeField(null=True, blank=True, default=None)
    jit_provisioning_enabled = models.BooleanField(
        default=False
    )  # Just-in-time automatic provisioning (user accounts are created on the respective org when logging in with any SSO provider)
    sso_enforcement = models.CharField(
        max_length=28, blank=True
    )  # currently only used for PostHog Cloud; SSO enforcement on self-hosted is set by env var

    # ---- SAML / SCIM / ID-JAG attributes (legacy, frozen) ----
    _saml_entity_id = models.CharField(
        max_length=512, blank=True, null=True, db_column="saml_entity_id"
    )  # deprecated, do not use; see `IdentityProviderConfig`
    _saml_acs_url = models.CharField(
        max_length=512, blank=True, null=True, db_column="saml_acs_url"
    )  # deprecated, do not use; see `IdentityProviderConfig`
    _saml_x509_cert = models.TextField(
        blank=True, null=True, db_column="saml_x509_cert"
    )  # deprecated, do not use; see `IdentityProviderConfig`

    _scim_enabled = models.BooleanField(
        default=False, db_column="scim_enabled"
    )  # deprecated, do not use; see `IdentityProviderConfig`
    _scim_bearer_token = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Hashed bearer token for SCIM authentication",
        db_column="scim_bearer_token",
    )  # deprecated, do not use; see `IdentityProviderConfig`

    _id_jag_issuer_url = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Trusted IdP issuer URL for ID-JAG. Required to enable ID-JAG on this domain.",
        db_column="id_jag_issuer_url",
    )  # deprecated, do not use; see `IdentityProviderConfig`

    # Defaults to `{id_jag_issuer_url}/.well-known/openid-configuration`.
    _id_jag_jwks_url = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Override JWKS URL. Defaults to OIDC discovery on the issuer URL.",
        db_column="id_jag_jwks_url",
    )  # deprecated, do not use; see `IdentityProviderConfig`
    _id_jag_allowed_clients = ArrayField(
        models.CharField(max_length=256),
        default=list,
        blank=True,
        null=True,
        help_text="Allowed ID-JAG client IDs. Empty list allows any client_id.",
        db_column="id_jag_allowed_clients",
    )  # deprecated, do not use; see `IdentityProviderConfig`

    _identity_provider_config = models.ForeignKey(
        IdentityProviderConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_column="identity_provider_config_id",
    )  # deprecated, do not use; see `LinkedIdentityProviderConfig`

    class Meta:
        verbose_name = "domain"

    @property
    def is_verified(self) -> bool:
        """
        Determines whether a domain is verified or not.
        """
        # TODO: Verification becomes stale on Cloud if not reverified after a certain period.
        return bool(self.verified_at)

    @property
    def identity_provider_configs(self) -> models.QuerySet[IdentityProviderConfig]:
        if self._state.adding:
            return IdentityProviderConfig.objects.none()
        return (
            IdentityProviderConfig.objects.filter(organization_id=self.organization_id)
            .annotate(
                is_explicitly_linked=models.Exists(
                    LinkedIdentityProviderConfig.objects.filter(
                        organization_domain=self, identity_provider_config=models.OuterRef("pk")
                    )
                )
            )
            .filter(models.Q(is_explicitly_linked=True) | models.Q(domain_scope=DomainScope.ALL))
            .order_by("-is_explicitly_linked", "created_at", "id")
        )

    def identity_provider_configs_for_scope(self, config_scope: str) -> models.QuerySet[IdentityProviderConfig]:
        return self.identity_provider_configs.filter(
            models.Q(config_scope=config_scope) | models.Q(config_scope__isnull=True)
        )

    @property
    def saml_identity_provider_configs(self) -> models.QuerySet[IdentityProviderConfig]:
        return self.identity_provider_configs_for_scope(ConfigScope.SAML).filter(saml_configured_q())

    def _complete_verification(self) -> tuple["OrganizationDomain", bool]:
        self.last_verification_retry = None
        self.verified_at = timezone.now()
        self.save()
        return (self, True)

    def attempt_verification(self) -> tuple["OrganizationDomain", bool]:
        """
        Performs a DNS verification for a specific domain.
        """
        try:
            dns_response = dnssec_resolver().resolve(f"_posthog-challenge.{self.domain}", "TXT")
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            pass
        else:
            for item in list(dns_response.response.answer[0]):
                if item.strings[0].decode() == self.verification_challenge:
                    return self._complete_verification()

        self.last_verification_retry = timezone.now()
        self.save()
        return (self, False)
