from typing import TYPE_CHECKING, Any

from django.db import models

from posthog.models.utils import UpdatedMetaFields, UUIDModel

if TYPE_CHECKING:
    from posthog.models.identity_provider_config import IdentityProviderConfig
    from posthog.models.user import User


class SCIMProvisionedUserManager(models.Manager["SCIMProvisionedUser"]):
    def for_config(self, config: "IdentityProviderConfig") -> models.QuerySet["SCIMProvisionedUser"]:
        """
        Every record belonging to a SCIM tenant: keyed on the config, or on one of the domains the
        config backs if it was written before SCIM moved onto configs.
        """
        return self.filter(
            models.Q(identity_provider_config=config) | models.Q(organization_domain__identity_provider_config=config)
        )

    def record_for(self, *, user: "User", config: "IdentityProviderConfig") -> "SCIMProvisionedUser | None":
        records = self.for_config(config).filter(user=user)
        return records.filter(identity_provider_config=config).first() or records.first()

    def upsert(
        self, *, user: "User", config: "IdentityProviderConfig", defaults: dict[str, Any]
    ) -> "SCIMProvisionedUser":
        """
        One record per (user, tenant). A record still keyed on a domain is claimed for the config
        rather than joined by a second one, so a user provisioned just before the config move isn't
        provisioned again after it.
        """
        record = self.record_for(user=user, config=config)
        if record is None:
            return self.create(user=user, identity_provider_config=config, **defaults)

        for field, value in defaults.items():
            setattr(record, field, value)
        record.identity_provider_config = config
        record.save(update_fields=[*defaults, "identity_provider_config", "updated_at"])
        return record


class SCIMProvisionedUser(UUIDModel, UpdatedMetaFields):
    class IdentityProvider(models.TextChoices):
        OKTA = "okta", "Okta"
        ENTRA_ID = "entra_id", "Microsoft Entra ID"
        GOOGLE = "google", "Google Workspace"
        ONELOGIN = "onelogin", "OneLogin"
        OTHER = "other", "Other"

    objects: SCIMProvisionedUserManager = SCIMProvisionedUserManager()

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
    # record to. Migration ee.0058 copied the config onto the rows that have one.
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
