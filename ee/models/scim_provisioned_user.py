from django.db import models

from posthog.models.utils import UpdatedMetaFields, UUIDModel


class SCIMProvisionedUser(UUIDModel, UpdatedMetaFields):
    class IdentityProvider(models.TextChoices):
        OKTA = "okta", "Okta"
        ENTRA_ID = "entra_id", "Microsoft Entra ID"
        GOOGLE = "google", "Google Workspace"
        ONELOGIN = "onelogin", "OneLogin"
        OTHER = "other", "Other"

    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="scim_provisions")
    # The SCIM tenant is the `IdentityProviderConfig` that owns the bearer token and the `scim_slug`
    # in the endpoint URL, so provisioning records hang off it.
    identity_provider_config = models.ForeignKey(
        "posthog.IdentityProviderConfig",
        on_delete=models.CASCADE,
        related_name="scim_provisioned_users",
        null=True,
        blank=True,
        db_index=False,
    )
    # Legacy tenant key, kept until the column is dropped. Don't write it: a SCIM request names a
    # config, and a config can back several domains, so there is no one domain to attribute a
    # record to. Migration ee.0058 copied the config onto the rows that have it.
    organization_domain = models.ForeignKey(
        "posthog.OrganizationDomain",
        on_delete=models.CASCADE,
        related_name="scim_provisioned_users",
        null=True,
        blank=True,
    )

    identity_provider = models.CharField(max_length=50, choices=IdentityProvider)
    username = models.CharField(max_length=255)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization_domain"],
                name="unique_user_organization_domain",
            ),
            models.UniqueConstraint(
                fields=["user", "identity_provider_config"],
                name="unique_user_identity_provider_config",
            ),
        ]
        indexes = [
            models.Index(fields=["organization_domain", "username"]),
            models.Index(fields=["identity_provider_config", "username"]),
        ]
