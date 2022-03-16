import secrets
from typing import Tuple

import dns.resolver
from django.conf import settings
from django.db import models
from django.utils import timezone

from posthog.models import Organization
from posthog.models.utils import UUIDModel


def generate_verification_challenge() -> str:
    return secrets.token_urlsafe(32)


class OrganizationDomain(UUIDModel):
    organization: models.OneToOneField = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="domains",
    )
    domain: models.CharField = models.CharField(max_length=128, unique=True)
    verification_challenge: models.CharField = models.CharField(max_length=128, default=generate_verification_challenge)
    verified_at: models.DateTimeField = models.DateTimeField(null=True, blank=True, default=None)
    last_verification_retry: models.DateTimeField = models.DateTimeField(null=True, blank=True, default=None)
    jit_provisioning_enabled: models.BooleanField = models.BooleanField(default=False)
    sso_enforcement: models.CharField = models.CharField(max_length=28, blank=True)

    def _complete_verification(self) -> Tuple["OrganizationDomain", bool]:
        self.last_verification_retry = None
        self.verified_at = timezone.now()
        self.save()
        return (self, True)

    def attempt_verification(self) -> Tuple["OrganizationDomain", bool]:
        """
        Performs a DNS verification for a specific domain.
        """

        if getattr(settings, "MULTI_TENANCY", False):
            # We only do DNS validation on PostHog Cloud
            return self._complete_verification()

        dns_response = []
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
