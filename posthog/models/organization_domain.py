import secrets
from typing import Optional, Tuple

import dns.resolver
import structlog
from django.conf import settings
from django.db import models
from django.utils import timezone

from posthog.constants import AvailableFeature
from posthog.models import Organization
from posthog.models.utils import UUIDModel
from posthog.utils import get_available_sso_providers

logger = structlog.get_logger(__name__)


def generate_verification_challenge() -> str:
    return secrets.token_urlsafe(32)


class OrganizationDomainManager(models.Manager):
    def verified_domains(self):
        # TODO: Verification becomes stale on Cloud if not reverified after a certain period.
        return self.exclude(verified_at__isnull=True)

    def get_sso_enforcement_for_email_address(self, email: str) -> Optional[str]:
        domain = email[email.index("@") + 1 :]
        query = (
            self.verified_domains()
            .filter(domain=domain)
            .exclude(sso_enforcement="")
            .values("sso_enforcement", "organization_id", "organization__available_features")
            .first()
        )

        if not query:
            return None

        candidate_sso_enforcement = query["sso_enforcement"]

        # Check organization has a license to enforce SSO
        if AvailableFeature.SSO_ENFORCEMENT not in query["organization__available_features"]:
            logger.warning(
                f"🤑🚪 SSO is enforced for domain {domain} but the organization does not have the proper license.",
                domain=domain,
                organization=str(query["organization_id"]),
            )
            return None

        # Check SSO provider is properly configured
        sso_providers = get_available_sso_providers()
        if not sso_providers[candidate_sso_enforcement]:
            logger.warning(
                f"SSO is enforced for domain {domain} but the SSO provider ({candidate_sso_enforcement}) is not properly configured.",
                domain=domain,
                candidate_sso_enforcement=candidate_sso_enforcement,
            )
            return None

        return candidate_sso_enforcement


class OrganizationDomain(UUIDModel):
    objects = OrganizationDomainManager()

    organization: models.ForeignKey = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="domains",
    )
    domain: models.CharField = models.CharField(max_length=128, unique=True)
    verification_challenge: models.CharField = models.CharField(max_length=128, default=generate_verification_challenge)
    verified_at: models.DateTimeField = models.DateTimeField(
        null=True, blank=True, default=None
    )  # verification (through DNS) is only used for PostHog Cloud; on self-hosted we take all domains as verified
    last_verification_retry: models.DateTimeField = models.DateTimeField(null=True, blank=True, default=None)
    jit_provisioning_enabled: models.BooleanField = models.BooleanField(
        default=False
    )  # Just-in-time automatic provisioning (user accounts are created on the respective org when logging in with any SSO provider)
    sso_enforcement: models.CharField = models.CharField(
        max_length=28, blank=True
    )  # currently only used for PostHog Cloud; SSO enforcement on self-hosted is set by env var

    class Meta:
        verbose_name = "domain"

    @property
    def is_verified(self) -> bool:
        """
        Determines whether a domain is verified or not.
        """
        # TODO: Verification becomes stale on Cloud if not reverified after a certain period.
        return bool(self.verified_at)

    def _complete_verification(self) -> Tuple["OrganizationDomain", bool]:
        self.last_verification_retry = None
        self.verified_at = timezone.now()
        self.save()
        return (self, True)

    def attempt_verification(self) -> Tuple["OrganizationDomain", bool]:
        """
        Performs a DNS verification for a specific domain.
        """

        if not getattr(settings, "MULTI_TENANCY", False):
            # We only do DNS validation on PostHog Cloud
            return self._complete_verification()

        try:
            # TODO: Should we manually validate DNSSEC?
            dns_response = dns.resolver.resolve(f"_posthog-challenge.{self.domain}", "TXT")
        except dns.resolver.NoAnswer:
            pass
        else:
            for item in list(dns_response.response.answer[0]):
                if item.strings[0].decode() == self.verification_challenge:
                    return self._complete_verification()

        self.last_verification_retry = timezone.now()
        self.save()
        return (self, False)
