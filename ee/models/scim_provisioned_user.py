from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, models, transaction

import structlog

from posthog.models.utils import UpdatedMetaFields, UUIDModel

if TYPE_CHECKING:
    from posthog.models.identity_provider_config import IdentityProviderConfig
    from posthog.models.user import User

logger = structlog.get_logger(__name__)


class SCIMProvisionedUserManager(models.Manager["SCIMProvisionedUser"]):
    def for_config(self, config: "IdentityProviderConfig") -> models.QuerySet["SCIMProvisionedUser"]:
        """
        Every record belonging to a SCIM tenant: the ones keyed on the config, plus the ones still
        unclaimed on a domain it backs. A record another config already holds stays out of scope
        even when they share a domain — an organization can run several IdPs, and one must not read
        or deprovision another's users.
        """
        return self.filter(
            models.Q(identity_provider_config=config)
            | models.Q(
                identity_provider_config__isnull=True,
                organization_domain__in=config.organization_domains,
            )
        )

    def record_for(self, *, user: "User", config: "IdentityProviderConfig") -> "SCIMProvisionedUser | None":
        records = self.for_config(config).filter(user=user).order_by("id")
        return records.filter(identity_provider_config=config).first() or records.first()

    def upsert(
        self, *, user: "User", config: "IdentityProviderConfig", defaults: dict[str, Any]
    ) -> "SCIMProvisionedUser":
        """
        One record per (user, tenant). A record still keyed on a domain is claimed for the config
        rather than joined by a second one, so a user provisioned just before the config move isn't
        provisioned again after it.
        """
        self._claim_record_keyed_on_a_domain(user=user, config=config)
        # `update_or_create` locks the row it finds and retries its own read if a concurrent insert
        # beats it, so the create side of this needs no handling here.
        record, _ = self.update_or_create(user=user, identity_provider_config=config, defaults=defaults)
        return record

    def _claim_record_keyed_on_a_domain(self, *, user: "User", config: "IdentityProviderConfig") -> None:
        unclaimed = (
            self.for_config(config).filter(user=user, identity_provider_config__isnull=True).order_by("id").first()
        )
        if unclaimed is None:
            return

        try:
            # The `isnull` filter makes a claim of the same record by a concurrent request a no-op
            # instead of an overwrite, and the savepoint keeps a lost race from poisoning the
            # transaction the caller is midway through.
            with transaction.atomic():
                self.filter(pk=unclaimed.pk, identity_provider_config__isnull=True).update(
                    identity_provider_config=config
                )
        except IntegrityError:
            # Someone else already holds (user, config) — their own record, or another domain-keyed
            # one they claimed first. Theirs wins, and `update_or_create` below finds it.
            logger.warning(
                "scim_provisioned_user_claim_lost",
                scim_provisioned_user_id=str(unclaimed.pk),
                identity_provider_config_id=str(config.pk),
            )


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
