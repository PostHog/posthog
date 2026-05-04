from __future__ import annotations

from django.db import models
from django.db.models.functions import Lower

from posthog.models.utils import UUIDModel


class RoleExternalReference(UUIDModel):
    """Maps an external provider role/group to a PostHog role.

    Organization-scoped: one external reference maps to exactly one role per org.
    A role can have many external references.

    Examples:
        GitHub team:  provider="github", provider_organization_id="posthog",
                      provider_role_id="12345", provider_role_slug="frontend-team", provider_role_name="Frontend Team"
        Linear team:  provider="linear", provider_organization_id="PostHog",
                      provider_role_id="abc-123", provider_role_slug="frontend", provider_role_name="Frontend"
        Jira project: provider="jira", provider_organization_id="posthog.atlassian.net",
                      provider_role_id="10001", provider_role_slug="FE", provider_role_name="Frontend"
        Slack channel: provider="slack", provider_organization_id="T01234567",
                       provider_role_id="C01234567", provider_role_slug="frontend", provider_role_name="#frontend"
    """

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="role_external_references",
    )
    role = models.ForeignKey(
        "ee.Role",
        on_delete=models.CASCADE,
        related_name="role_external_references",
    )

    # Which integration kind this comes from (reuses Integration.IntegrationKind values)
    provider = models.CharField(max_length=32)
    # The org/workspace/site on the provider side
    provider_organization_id = models.CharField(max_length=255)
    # Stable external ID (numeric for GitHub, UUID for Linear, etc.)
    provider_role_id = models.CharField(max_length=255)
    # Human-friendly identifier (slug, key, channel name) — used for CODEOWNERS-style lookups
    provider_role_slug = models.CharField(max_length=255, null=True, blank=True)
    # Display name
    provider_role_name = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("provider_organization_id"),
                Lower("provider_role_slug"),
                "organization",
                "provider",
                name="unique_role_ext_ref_slug_per_org",
            ),
            models.UniqueConstraint(
                Lower("provider_organization_id"),
                Lower("provider_role_id"),
                "organization",
                "provider",
                name="unique_role_ext_ref_id_per_org",
            ),
        ]
        indexes = [
            models.Index(
                fields=["provider", "provider_organization_id", "provider_role_slug"],
                name="idx_role_ext_ref_slug_lookup",
            ),
            models.Index(
                fields=["provider", "provider_organization_id", "provider_role_id"],
                name="idx_role_ext_ref_id_lookup",
            ),
        ]
