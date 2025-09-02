import secrets
from typing import Optional

from django.db import models
from django.utils import timezone

import structlog
import dns.resolver

from posthog.constants import AvailableFeature
from posthog.models import Organization
from posthog.models.utils import UUIDTModel
from posthog.utils import get_instance_available_sso_providers

logger = structlog.get_logger(__name__)


def generate_verification_challenge() -> str:
    return secrets.token_urlsafe(32)


class OrganizationDomainManager(models.Manager):
    def verified_domains(self):
        # TODO: Verification becomes stale on Cloud if not reverified after a certain period.
        return self.exclude(verified_at__isnull=True)

    def get_verified_for_email_address(self, email: str) -> Optional["OrganizationDomain"]:
        """
        Returns an `OrganizationDomain` configuration for a specific email address (if it exists and is verified),
        using the domain of the email address
        """
        domain = email[email.index("@") + 1 :]
        return self.verified_domains().filter(domain__iexact=domain).first()

    def get_is_saml_available_for_email(self, email: str) -> bool:
        """
        Returns whether SAML is available for a specific email address.
        """
        domain = email[email.index("@") + 1 :]
        query = (
            self.verified_domains()
            .filter(domain__iexact=domain)
            .exclude(
                models.Q(saml_entity_id="")
                | models.Q(saml_acs_url="")
                | models.Q(saml_x509_cert="")
                | models.Q(
                    saml_entity_id__isnull=True
                )  # normally we would have just a nil state (i.e. ""), but to avoid migration locks we had to introduce this
                | models.Q(saml_acs_url__isnull=True)
                | models.Q(saml_x509_cert__isnull=True)
            )
            .values_list("organization__available_product_features", flat=True)
            .first()
        )

        if query is None:
            return False

        for feature in query:
            if feature.get("key") == AvailableFeature.SAML:
                return True
        return False

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


class OrganizationDomain(UUIDTModel):
    objects: OrganizationDomainManager = OrganizationDomainManager()

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

    # ---- SAML attributes ----
    # Normally not good practice to have `null=True` in `CharField` (as you have to nil states now), but creating non-nullable
    # attributes locks up tables when migrating. Remove `null=True` on next major release.
    saml_entity_id = models.CharField(max_length=512, blank=True, null=True)
    saml_acs_url = models.CharField(max_length=512, blank=True, null=True)
    saml_x509_cert = models.TextField(blank=True, null=True)

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
    def has_saml(self) -> bool:
        """
        Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places).
        """
        return bool(self.saml_entity_id) and bool(self.saml_acs_url) and bool(self.saml_x509_cert)

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
            # TODO: Should we manually validate DNSSEC?
            dns_response = dns.resolver.resolve(f"_posthog-challenge.{self.domain}", "TXT")
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            pass
        else:
            for item in list(dns_response.response.answer[0]):
                if item.strings[0].decode() == self.verification_challenge:
                    return self._complete_verification()

        self.last_verification_retry = timezone.now()
        self.save()
        return (self, False)
